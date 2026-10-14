"""Find prescription drug labels (SPLs) in openFDA that carry no prescribing text at all.

A "hollow" label is a HUMAN PRESCRIPTION DRUG label with none of the sections
indications_and_usage, dosage_and_administration, warnings_and_cautions and
warnings: only product data, package-label text and perhaps an empty
Medication Guide heading. DailyMed shows such a label as the product's label,
so a reader sees no indications, no dosing and no boxed warning.

Each hollow label is sorted into a kind (medical gas, blood-collection
solution, or drug), and for each drug we ask openFDA two more questions about
the same generic name: which labelers' labels carry a boxed warning, and which
labelers have a label with full prescribing text. That tells us whether the
missing text matters (the drug has a boxed warning elsewhere) and whether the
same company publishes the text under another label.

Research data, not medical advice: a listed SPL says nothing about the paper
insert in the box or what a pharmacy dispenses. Standard library only.
Apache-2.0. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name.
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.fda.gov/drug/label.json"
USER_AGENT = "asof-kg hollow-spl (MV2 of Munim, Inc.; munimversion2@gmail.com)"
TEXT_SECTIONS = ("indications_and_usage", "dosage_and_administration", "warnings_and_cautions", "warnings")
RX = 'openfda.product_type:"HUMAN PRESCRIPTION DRUG"'
HOLLOW = RX + "".join(" AND _missing_:" + s for s in TEXT_SECTIONS)
PAGE = 1000

GAS_WORDS = {"OXYGEN", "NITROGEN", "NITROUS", "OXIDE", "CARBON", "DIOXIDE", "AIR", "HELIUM", "CARBOGEN",
             "HELIOX", "MIXTURE", "MIX", "COMPRESSED", "RECONSTITUTED", "MEDICAL", "AND", "USP", "NF"}
BLOOD_WORDS = ("ANTICOAGULANT", "CPDA", "CP2D", "BLOOD BAG", "ADDITIVE SYSTEM", "ADSOL")

COLUMNS = ("set_id", "spl_version", "effective_time", "manufacturer", "generic_name", "brand_name", "routes",
           "kind", "sections", "boxed_labels_of_generic", "boxed_labelers_of_generic", "labeler_has_full_text",
           "family_has_full_text")


def kind_of(generic):
    """'gas', 'blood' or 'drug' for a generic name."""
    name = generic.upper()
    if any(word in name for word in BLOOD_WORDS):
        return "blood"
    words = [w for w in re.split(r"[^A-Z0-9]+", name) if w]
    if words and all(w in GAS_WORDS for w in words):
        return "gas"
    return "drug"


def family(manufacturer):
    """A loose company family key: the first word of the labeler name, lower case."""
    words = re.findall(r"[a-z0-9]+", manufacturer.lower())
    return words[0] if words else ""


def first(record, key):
    values = record.get("openfda", {}).get(key, [])
    return values[0] if values else ""


def sections(record):
    """The record's content keys, apart from ids, dates and openFDA's annotations."""
    return sorted(k for k in record if k not in ("id", "set_id", "version", "effective_time", "openfda"))


def is_hollow(record):
    return not any(record.get(s) for s in TEXT_SECTIONS) and not record.get("boxed_warning")


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


def row_for(record, facts):
    """One CSV row. ``facts`` maps a generic name to what openFDA says about its other labels:
    {"boxed": n, "boxed_labelers": [names], "full_text_labelers": [names]}."""
    generic = first(record, "generic_name")
    manufacturer = first(record, "manufacturer_name")
    kind = kind_of(generic)
    known = facts.get(generic)
    row = {
        "set_id": record.get("set_id", ""),
        "spl_version": record.get("version", ""),
        "effective_time": record.get("effective_time", ""),
        "manufacturer": manufacturer,
        "generic_name": generic,
        "brand_name": first(record, "brand_name"),
        "routes": "|".join(record.get("openfda", {}).get("route", [])),
        "kind": kind,
        "sections": "|".join(sections(record)),
        "boxed_labels_of_generic": "", "boxed_labelers_of_generic": "",
        "labeler_has_full_text": "", "family_has_full_text": "",
    }
    if kind == "drug" and known is not None:
        full = known["full_text_labelers"]
        row["boxed_labels_of_generic"] = known["boxed"]
        row["boxed_labelers_of_generic"] = len(known["boxed_labelers"])
        row["labeler_has_full_text"] = "yes" if manufacturer in full else "no"
        row["family_has_full_text"] = "yes" if family(manufacturer) in {family(m) for m in full} else "no"
    return row


def summarise(rows, rx_total):
    """Counts for summary.json."""
    by_kind, drug_labelers, boxed_labelers = {}, {}, {}
    boxed_rows, orphan_rows = [], []
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        if r["kind"] != "drug":
            continue
        drug_labelers[r["manufacturer"]] = drug_labelers.get(r["manufacturer"], 0) + 1
        if r["boxed_labels_of_generic"] not in ("", 0):
            boxed_rows.append(r)
            boxed_labelers[r["manufacturer"]] = boxed_labelers.get(r["manufacturer"], 0) + 1
            if r["family_has_full_text"] == "no":
                orphan_rows.append(r)
    top = sorted(drug_labelers.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "rx_labels": rx_total,
        "hollow_labels": len(rows),
        "by_kind": by_kind,
        "drug_labels_by_labeler": dict(top),
        "hollow_drug_labels_whose_generic_has_a_boxed_warning": len(boxed_rows),
        "of_which_no_full_text_label_from_the_same_company_family": len(orphan_rows),
        "boxed_by_labeler": dict(sorted(boxed_labelers.items(), key=lambda kv: (-kv[1], kv[0]))),
        "boxed_generics": sorted({r["generic_name"] for r in boxed_rows}),
        "orphan_set_ids": sorted(r["set_id"] for r in orphan_rows),
    }


def write(rows, summary, out, meta):
    os.makedirs(out, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["kind"], r["manufacturer"], r["generic_name"], r["set_id"]))
    with open(os.path.join(out, "hollow.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": summary}, f, indent=2)
    s = summary
    lines = ["# Prescription labels in openFDA with no prescribing text (%s)" % meta["run_date"], "",
             "- Human prescription drug labels in openFDA: %d" % s["rx_labels"],
             "- Hollow (no indications, dosage, warnings or boxed warning): %d" % s["hollow_labels"],
             "- By kind: " + ", ".join("%s %d" % kv for kv in sorted(s["by_kind"].items())),
             "- Hollow drug labels whose generic carries a boxed warning in other openFDA labels: %d"
             % s["hollow_drug_labels_whose_generic_has_a_boxed_warning"],
             "- ... of which no labeler in the same company family has a full-text label of that generic: %d"
             % s["of_which_no_full_text_label_from_the_same_company_family"],
             "", "## Hollow drug labels by labeler", "", "| Labeler | Hollow drug labels | With a boxed-warning generic |",
             "|---|---|---|"]
    for name, n in s["drug_labels_by_labeler"].items():
        lines.append("| %s | %d | %d |" % (name, n, s["boxed_by_labeler"].get(name, 0)))
    lines += ["", "## Hollow drug labels whose generic carries a boxed warning elsewhere", "",
              "| Generic | Labeler | Effective | Set id | Same family has full text |", "|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] == "drug" and r["boxed_labels_of_generic"] not in ("", 0):
            lines.append("| %s | %s | %s | %s | %s |" % (r["generic_name"], r["manufacturer"], r["effective_time"],
                                                     r["set_id"], r["family_has_full_text"]))
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def get(params, pause=0.35, tries=6):
    """One openFDA query; None when nothing matches (HTTP 404)."""
    request = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                page = json.loads(response.read().decode("utf-8"))
            time.sleep(pause)
            return page
        except urllib.error.HTTPError as e:
            if e.code == 404:
                time.sleep(pause)
                return None
            if attempt == tries - 1:
                raise
        except urllib.error.URLError:
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt * (10 if attempt else 2))
    return None


def total(search):
    page = get({"search": search, "limit": 1})
    return page["meta"]["results"]["total"] if page else 0


def fetch_hollow():
    records, skip, count = [], 0, None
    while count is None or skip < count:
        page = get({"search": HOLLOW, "limit": PAGE, "skip": skip})
        if not page:
            break
        count = page["meta"]["results"]["total"]
        records.extend(page.get("results", []))
        skip += PAGE
    return records


def quote(value):
    return '"%s"' % value.replace('"', "")


def labelers(search):
    """{labeler: label count} for an openFDA search (two queries per generic keep us under
    openFDA's keyless limit of 1,000 requests a day)."""
    page = get({"search": search, "count": "openfda.manufacturer_name.exact", "limit": 1000})
    return {b["term"]: b["count"] for b in page["results"]} if page else {}


def facts_for(generic):
    name = "openfda.generic_name.exact:" + quote(generic)
    boxed = labelers(name + " AND _exists_:boxed_warning")
    return {"boxed": sum(boxed.values()), "boxed_labelers": sorted(boxed),
            "full_text_labelers": sorted(labelers(name + " AND _exists_:indications_and_usage"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="out")
    args = parser.parse_args(argv)

    rx_total = total(RX)
    records = [r for r in latest_per_set(fetch_hollow()) if is_hollow(r)]
    print("hollow records: %d of %d prescription labels" % (len(records), rx_total), file=sys.stderr)
    generics = sorted({first(r, "generic_name") for r in records
                       if first(r, "generic_name") and kind_of(first(r, "generic_name")) == "drug"})
    facts = {}
    for i, generic in enumerate(generics, 1):
        facts[generic] = facts_for(generic)
        if i % 25 == 0:
            print("generics checked: %d/%d" % (i, len(generics)), file=sys.stderr)
    rows = [row_for(r, facts) for r in records]
    meta = {"run_date": dt.date.today().isoformat(), "source": API, "query": HOLLOW,
            "note": "Research data, not medical advice. openFDA says its data are unvalidated."}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "facts.json"), "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=1, sort_keys=True)
    print(write(rows, summarise(rows, rx_total), args.out, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
