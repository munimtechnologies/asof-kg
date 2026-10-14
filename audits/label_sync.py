"""Check every drug label openFDA serves today against the dated history of the drug's boxed warning.

For each drug in asof-kg's fda_boxed_warnings.json (levofloxacin, varenicline,
montelukast, febuxostat, tofacitinib), fetch every label (SPL) in openFDA's
drug label endpoint and compare its boxed warning with the newest version FDA
approved. Each label copy is:

- current: its boxed warning names every risk the newest version names, and
  none that a later version removed;
- stale: it lacks a required risk, or still carries one FDA approved removing;
- unparsed: openFDA has no boxed_warning field for it, but another section
  refers to a boxed warning or holds a "WARNING: ..." heading naming a
  required risk, so the warning is probably there in a form openFDA did not
  split out (seen on DailyMed for an AvKARE montelukast label). These are
  counted apart, never as stale.
- no_text: the label has no prescribing text at all (no indications, dosage
  or warnings sections; only product data and package-label text). The SPL
  itself is empty, as DailyMed shows for Zydus Lifesciences' levofloxacin
  label, so it is counted apart from stale copies (see hollow_spl.py).

Research data, not medical advice: a stale copy in a database says nothing
about what a pharmacy hands out. Standard library only. Apache-2.0.
Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name.
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.fda.gov/drug/label.json"
HISTORY = "https://raw.githubusercontent.com/munimtechnologies/asof-kg/main/asofkg/data/fda_boxed_warnings.json"
PAGE = 100
USER_AGENT = "asof-kg label-sync (MV2 of Munim, Inc.; munimversion2@gmail.com)"
TEXT_SECTIONS = ("indications_and_usage", "dosage_and_administration", "warnings_and_cautions", "warnings")

# Words that show a risk is named in a boxed warning's text (lower case).
RISK_WORDS = {
    "tendinitis and tendon rupture": ["tendon"],
    "exacerbation of myasthenia gravis": ["myasthenia"],
    "disabling and potentially irreversible serious adverse reactions": ["disabling"],
    "peripheral neuropathy": ["neuropathy"],
    "central nervous system effects": ["central nervous system", "cns effects"],
    "serious neuropsychiatric events": ["neuropsychiatric"],
    "cardiovascular death": ["cardiovascular death"],
    "serious infections": ["infection"],
    "mortality": ["mortality"],
    "malignancy": ["malignan"],
    "major adverse cardiovascular events": ["major adverse cardiovascular", "(mace)"],
    "thrombosis": ["thrombosis"],
}

# Products of the same ingredient that never carried the boxed warning.
EXCLUDED_ROUTES = {"levofloxacin": {"OPHTHALMIC"}}

STATUSES = ("current", "stale", "unparsed", "no_text")
COLUMNS = ("drug", "set_id", "spl_version", "effective_time", "manufacturer", "brand_name", "routes",
           "status", "missing", "carried", "agrees_with", "stale_since", "days_after_change")


def load_history(source=HISTORY):
    """Label versions per drug, oldest first, from a path or URL of fda_boxed_warnings.json."""
    if source.startswith("http"):
        request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = json.loads(response.read().decode("utf-8"))
    else:
        with open(source, encoding="utf-8") as f:
            raw = json.load(f)
    chains = {}
    for v in raw["versions"]:
        chains.setdefault(v["subject"], []).append(v)
    for versions in chains.values():
        versions.sort(key=lambda v: v["effective"])
    return chains


def risks_in(text, risks):
    """The risks, from ``risks``, that ``text`` names."""
    text = text.lower()
    return [r for r in risks if any(word in text for word in RISK_WORDS.get(r, [r.lower()]))]


def label_day(value):
    """openFDA's effective_time (YYYYMMDD) as a date, or None."""
    try:
        return dt.datetime.strptime(str(value)[:8], "%Y%m%d").date()
    except ValueError:
        return None


def refers_to_box(record, risks=()):
    """True if a section other than boxed_warning mentions a boxed warning, or holds a
    "WARNING: ..." heading that names one of ``risks`` (a box openFDA did not split out)."""
    for key, value in record.items():
        if key in ("boxed_warning", "openfda") or not isinstance(value, list):
            continue
        for part in value:
            if not isinstance(part, str):
                continue
            text = part.lower()
            if "boxed warning" in text:
                return True
            at = text.find("warning:")
            while at >= 0:
                if risks_in(text[at:at + 300], risks):
                    return True
                at = text.find("warning:", at + 1)
    return False


def has_text(record):
    """True if the label has any prescribing text section."""
    return any(record.get(s) for s in TEXT_SECTIONS)


def _box(version):
    return list(version["facts"].get("boxed_warning", []))


def classify(record, versions):
    """Compare one openFDA label record with a drug's versions (oldest first); returns a dict."""
    expected = _box(versions[-1])
    every = []
    for v in versions:
        every.extend(r for r in _box(v) if r not in every)
    removed = [r for r in every if r not in expected]
    boxed = " ".join(part for part in record.get("boxed_warning", []) if isinstance(part, str))
    found = risks_in(boxed, every) if boxed.strip() else []
    missing = [r for r in expected if r not in found]
    carried = [r for r in removed if r in found]

    if boxed.strip():
        status = "stale" if missing or carried else "current"
    elif not expected:
        status = "current"
    elif refers_to_box(record, expected):
        status = "unparsed"
    elif not has_text(record):
        status = "no_text"
    else:
        status = "stale"

    agrees = []
    stale_since = None
    if status in ("current", "stale"):
        agrees = [v["id"] for v in versions if set(_box(v)) == set(found)]
    if status == "stale":
        changes = []
        for risk in missing:
            changes.append(min(v["effective"] for v in versions if risk in _box(v)))
        for risk in carried:
            changes.append(min(v["effective"] for v in versions
                               if risk not in _box(v) and v["effective"] > _first_with(versions, risk)))
        stale_since = dt.date.fromisoformat(min(changes))
    day = label_day(record.get("effective_time", ""))
    return {"status": status, "missing": missing, "carried": carried, "agrees_with": agrees,
            "stale_since": stale_since,
            "days_after_change": (day - stale_since).days if day and stale_since else None}


def _first_with(versions, risk):
    return min(v["effective"] for v in versions if risk in _box(v))


def row_for(drug, record, versions):
    openfda = record.get("openfda", {})
    result = classify(record, versions)
    return {
        "drug": drug,
        "set_id": record.get("set_id", ""),
        "spl_version": record.get("version", ""),
        "effective_time": record.get("effective_time", ""),
        "manufacturer": "|".join(openfda.get("manufacturer_name", [])),
        "brand_name": "|".join(openfda.get("brand_name", [])),
        "routes": "|".join(openfda.get("route", [])),
        "status": result["status"],
        "missing": "|".join(result["missing"]),
        "carried": "|".join(result["carried"]),
        "agrees_with": "|".join(result["agrees_with"]),
        "stale_since": result["stale_since"].isoformat() if result["stale_since"] else "",
        "days_after_change": "" if result["days_after_change"] is None else result["days_after_change"],
    }


def excluded(drug, record):
    """True for a product whose routes all lie outside the labels the history covers."""
    routes = set(record.get("openfda", {}).get("route", []))
    skip = EXCLUDED_ROUTES.get(drug, set())
    return bool(routes) and routes <= skip


def latest_per_set(records):
    """One record per SPL set id, the highest version."""
    best = {}
    for record in records:
        key = record.get("set_id") or record.get("id")
        try:
            number = int(record.get("version", 0))
        except ValueError:
            number = 0
        if key not in best or number > best[key][0]:
            best[key] = (number, record)
    return [record for _, record in best.values()]


def audit(records_by_drug, history):
    """Rows (one per label copy) and a per-drug summary."""
    rows, summary = [], {}
    for drug in sorted(records_by_drug):
        counts = {"labels": 0, "excluded_route": 0}
        counts.update((s, 0) for s in STATUSES)
        for record in latest_per_set(records_by_drug[drug]):
            if excluded(drug, record):
                counts["excluded_route"] += 1
                continue
            row = row_for(drug, record, history[drug])
            counts["labels"] += 1
            counts[row["status"]] += 1
            rows.append(row)
        counts["newest_version"] = history[drug][-1]["id"]
        counts["newest_boxed_warning"] = _box(history[drug][-1])
        summary[drug] = counts
    return rows, summary


def fetch(drug, pause=0.3, tries=4):
    """Every openFDA drug label record whose generic name is ``drug``."""
    records, skip, total = [], 0, None
    while total is None or skip < total:
        query = urllib.parse.urlencode({"search": 'openfda.generic_name:"%s"' % drug, "limit": PAGE, "skip": skip})
        request = urllib.request.Request(API + "?" + query, headers={"User-Agent": USER_AGENT})
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    page = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return records
                if attempt == tries - 1:
                    raise
            except urllib.error.URLError:
                if attempt == tries - 1:
                    raise
            time.sleep(2 ** attempt)
        total = page["meta"]["results"]["total"]
        records.extend(page.get("results", []))
        skip += PAGE
        time.sleep(pause)
    return records


def write(rows, summary, out, meta):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "labels.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "drugs": summary}, f, indent=2)
    lines = ["# openFDA label copies vs. FDA's newest boxed warning (%s)" % meta["run_date"], "",
             "| Drug | Labels | Current | Stale | Unparsed | No text | Excluded (route) |",
             "|---|---|---|---|---|---|---|"]
    for drug, c in summary.items():
        lines.append("| %s | %d | %d | %d | %d | %d | %d |" % (drug, c["labels"], c["current"], c["stale"],
                                                           c["unparsed"], c["no_text"], c["excluded_route"]))
    lines += ["", "## Stale copies", "",
              "| Drug | Manufacturer | Effective | Missing | Still carries | Agrees with | Days after the change |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] == "stale":
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                r["drug"], r["manufacturer"], r["effective_time"], r["missing"] or "-", r["carried"] or "-",
                r["agrees_with"] or "-", r["days_after_change"]))
    lines += ["", "## Labels with no prescribing text", "", "| Drug | Manufacturer | Effective | Set id |",
              "|---|---|---|---|"]
    for r in rows:
        if r["status"] == "no_text":
            lines.append("| %s | %s | %s | %s |" % (r["drug"], r["manufacturer"], r["effective_time"], r["set_id"]))
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--history", default=HISTORY, help="path or URL of fda_boxed_warnings.json")
    parser.add_argument("--out", default="out")
    parser.add_argument("--raw", help="also save the fetched openFDA records here (JSON per drug)")
    args = parser.parse_args(argv)

    history = load_history(args.history)
    records = {}
    for drug in sorted(history):
        records[drug] = fetch(drug)
        print("%s: %d records" % (drug, len(records[drug])), file=sys.stderr)
        if args.raw:
            os.makedirs(args.raw, exist_ok=True)
            with open(os.path.join(args.raw, drug + ".json"), "w", encoding="utf-8") as f:
                json.dump(records[drug], f)
    rows, summary = audit(records, history)
    meta = {"run_date": dt.date.today().isoformat(), "source": API, "history": args.history,
            "note": "Research data, not medical advice. openFDA says its data are unvalidated."}
    print(write(rows, summary, args.out, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
