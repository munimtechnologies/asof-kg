"""Find prescription drug labels (SPLs) in openFDA that carry no prescribing text at all.

A candidate is a HUMAN PRESCRIPTION DRUG label with none of the sections
indications_and_usage, dosage_and_administration, warnings_and_cautions,
warnings and boxed_warning. Version 2 splits candidates in two:

- ``no_text``: apart from the product data and the package label, the label
  holds at most TEXT_MIN characters (an empty Medication Guide heading, say).
  DailyMed shows such a label as the product's label, so a reader sees no
  indications, no dosing and no boxed warning. These are the hollow labels.
- ``uncoded_text``: the text is there but sits in unclassified sections
  (LOINC 42229-5) instead of coded ones. Bausch Health's Efudex label is one.

Each hollow label is sorted into a kind (medical gas, blood-collection
solution, or drug). For each drug we ask openFDA, for the same generic name
AND the same route, how many prescription labels carry a boxed warning and how
many carry full text. A drug "has a boxed warning" when at least BOXED_SHARE
of its full-text labels carry one, so a stray box on one copy (azithromycin)
or a box that belongs to another route (fluorouracil injection vs. cream) no
longer counts. For hollow labels of boxed drugs we also list which labelers
publish full text under the same application number (ANDA/NDA).

Version 2.1 files gas mixtures with numbers in their names ("OXYGEN/HELIUM
20/80", "AIR 90% CARBON DIOXIDE 10%") and refrigerated or breathing gases as
gases rather than drugs, and writes each label's product NDCs for ndc_lookup.py.

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
USER_AGENT = "asof-kg hollow-spl/2.1 (MV2 of Munim, Inc.; munimversion2@gmail.com)"
TEXT_SECTIONS = ("indications_and_usage", "dosage_and_administration", "warnings_and_cautions", "warnings")
RX = 'openfda.product_type:"HUMAN PRESCRIPTION DRUG"'
HOLLOW = RX + "".join(" AND _missing_:" + s for s in TEXT_SECTIONS + ("boxed_warning",))
PAGE = 1000
TEXT_MIN = 200
BOXED_SHARE = 0.5
NOT_TEXT = {"id", "set_id", "version", "effective_time", "openfda",
            "spl_product_data_elements", "package_label_principal_display_panel"}

GAS_WORDS = {"OXYGEN", "NITROGEN", "NITROUS", "OXIDE", "CARBON", "DIOXIDE", "AIR", "HELIUM", "CARBOGEN",
             "HELIOX", "MIXTURE", "MIX", "COMPRESSED", "RECONSTITUTED", "MEDICAL", "AND", "USP", "NF",
             "GAS", "REFRIGERATED", "LIQUID", "BREATHING", "U", "S", "P", "0XYGEN"}
BLOOD_WORDS = ("ANTICOAGULANT", "CPDA", "CP2D", "BLOOD BAG", "ADDITIVE SYSTEM", "ADSOL")

COLUMNS = ("set_id", "spl_version", "effective_time", "manufacturer", "generic_name", "brand_name", "routes",
           "application", "kind", "text_status", "free_text_chars", "sections", "boxed_labels",
           "full_text_labels", "boxed_share", "boxed", "labeler_has_full_text", "family_has_full_text",
           "same_application_full_text", "product_ndcs")


def kind_of(generic):
    """'gas', 'blood' or 'drug' for a generic name. Numbers (mixture ratios) don't make a gas a drug."""
    name = generic.upper()
    if any(word in name for word in BLOOD_WORDS):
        return "blood"
    words = [w for w in re.split(r"[^A-Z0-9]+", name) if w]
    if words and all(w in GAS_WORDS or w.isdigit() for w in words) and not all(w.isdigit() for w in words):
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


def is_candidate(record):
    return not any(record.get(s) for s in TEXT_SECTIONS) and not record.get("boxed_warning")


def free_text(record):
    """Characters of text outside the product data, the package label and tables."""
    n = 0
    for key, value in record.items():
        if key in NOT_TEXT or key.endswith("_table") or not isinstance(value, list):
            continue
        n += sum(len(v.strip()) for v in value if isinstance(v, str))
    return n


def text_status(record):
    return "no_text" if free_text(record) <= TEXT_MIN else "uncoded_text"


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


def fact_key(generic, route):
    return generic + "|" + route


def boxed_share(known):
    """Boxed labels over full-text labels for one generic and route."""
    boxed = sum(known["boxed"].values())
    full = sum((known["full_text"] or {}).values())
    if not full:
        return 1.0 if boxed else 0.0
    return round(min(boxed / full, 1.0), 3)


def row_for(record, facts, app_text):
    """One CSV row. ``facts`` maps "GENERIC|ROUTE" to {"boxed": {labeler: n}, "full_text": {labeler: n} or None}
    (None: not fetched, because v1 found no boxed label of that generic anywhere). ``app_text`` maps an
    application number to the labelers with a full-text label under it."""
    generic = first(record, "generic_name")
    manufacturer = first(record, "manufacturer_name")
    route = first(record, "route")
    application = first(record, "application_number")
    kind = kind_of(generic)
    status = text_status(record)
    row = {
        "set_id": record.get("set_id", ""),
        "spl_version": record.get("version", ""),
        "effective_time": record.get("effective_time", ""),
        "manufacturer": manufacturer,
        "generic_name": generic,
        "brand_name": first(record, "brand_name"),
        "routes": "|".join(record.get("openfda", {}).get("route", [])),
        "application": application,
        "kind": kind,
        "text_status": status,
        "free_text_chars": free_text(record),
        "sections": "|".join(sections(record)),
        "boxed_labels": "", "full_text_labels": "", "boxed_share": "", "boxed": "",
        "labeler_has_full_text": "", "family_has_full_text": "", "same_application_full_text": "",
        "product_ndcs": "|".join(record.get("openfda", {}).get("product_ndc", [])),
    }
    known = facts.get(fact_key(generic, route))
    if kind != "drug" or status != "no_text" or known is None:
        return row
    share = boxed_share(known)
    row["boxed_labels"] = sum(known["boxed"].values())
    row["boxed_share"] = share
    row["boxed"] = "yes" if share >= BOXED_SHARE else "no"
    full = known["full_text"]
    if full is not None:
        row["full_text_labels"] = sum(full.values())
        row["labeler_has_full_text"] = "yes" if manufacturer in full else "no"
        row["family_has_full_text"] = "yes" if family(manufacturer) in {family(m) for m in full} else "no"
    if application in app_text:
        row["same_application_full_text"] = "|".join(app_text[application])
    return row


def summarise(rows, rx_total, rx_by_labeler):
    """Counts for summary.json. ``rx_by_labeler``: all prescription labels per labeler in openFDA."""
    hollow = [r for r in rows if r["text_status"] == "no_text"]
    by_kind, drug_labelers, boxed_labelers = {}, {}, {}
    boxed_rows, orphan_rows = [], []
    for r in hollow:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        if r["kind"] != "drug":
            continue
        drug_labelers[r["manufacturer"]] = drug_labelers.get(r["manufacturer"], 0) + 1
        if r["boxed"] == "yes":
            boxed_rows.append(r)
            boxed_labelers[r["manufacturer"]] = boxed_labelers.get(r["manufacturer"], 0) + 1
            if r["family_has_full_text"] == "no":
                orphan_rows.append(r)
    top = sorted(drug_labelers.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "rx_labels": rx_total,
        "candidates": len(rows),
        "uncoded_text": len(rows) - len(hollow),
        "hollow_labels": len(hollow),
        "by_kind": by_kind,
        "drug_labels_by_labeler": dict(top),
        "rx_labels_of_labeler": {name: rx_by_labeler.get(name, 0) for name, _ in top},
        "hollow_drug_labels_with_boxed_warning_drug": len(boxed_rows),
        "of_which_no_full_text_label_from_the_same_company_family": len(orphan_rows),
        "boxed_by_labeler": dict(sorted(boxed_labelers.items(), key=lambda kv: (-kv[1], kv[0]))),
        "boxed_generics": sorted({r["generic_name"] for r in boxed_rows}),
        "orphan_set_ids": sorted(r["set_id"] for r in orphan_rows),
        "uncoded_set_ids": sorted(r["set_id"] for r in rows if r["text_status"] == "uncoded_text"),
    }


def write(rows, summary, out, meta):
    os.makedirs(out, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["text_status"], r["kind"], r["manufacturer"], r["generic_name"], r["set_id"]))
    with open(os.path.join(out, "hollow.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": summary}, f, indent=2)
    s = summary
    lines = ["# Prescription labels in openFDA with no prescribing text (%s, v2)" % meta["run_date"], "",
             "- Human prescription drug labels in openFDA: %d" % s["rx_labels"],
             "- With no indications, dosage, warnings or boxed-warning section: %d" % s["candidates"],
             "- ... of which the text sits in unclassified sections (not hollow): %d" % s["uncoded_text"],
             "- Hollow (at most %d characters of text besides product data and package label): %d"
             % (TEXT_MIN, s["hollow_labels"]),
             "- Hollow by kind: " + ", ".join("%s %d" % kv for kv in sorted(s["by_kind"].items())),
             "- Hollow drug labels of a drug whose same-route labels mostly carry a boxed warning: %d"
             % s["hollow_drug_labels_with_boxed_warning_drug"],
             "- ... of which no labeler in the same company family has a full-text label: %d"
             % s["of_which_no_full_text_label_from_the_same_company_family"],
             "", "## Hollow drug labels by labeler", "",
             "| Labeler | Hollow drug labels | Prescription labels in openFDA | With a boxed-warning drug |",
             "|---|---|---|---|"]
    for name, n in s["drug_labels_by_labeler"].items():
        lines.append("| %s | %d | %d | %d |" % (name, n, s["rx_labels_of_labeler"].get(name, 0),
                                               s["boxed_by_labeler"].get(name, 0)))
    lines += ["", "## Hollow labels of boxed-warning drugs", "",
              "| Generic | Route | Labeler | Effective | Set id | Boxed share | Family has full text |"
              " Full text under the same application |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["text_status"] == "no_text" and r["boxed"] == "yes":
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["generic_name"], r["routes"], r["manufacturer"], r["effective_time"], r["set_id"],
                r["boxed_share"], r["family_has_full_text"], r["same_application_full_text"] or "-"))
    lines += ["", "## Labels whose text is in unclassified sections", "", "| Generic | Labeler | Set id | Characters |",
              "|---|---|---|---|"]
    for r in rows:
        if r["text_status"] == "uncoded_text":
            lines.append("| %s | %s | %s | %d |" % (r["generic_name"], r["manufacturer"], r["set_id"],
                                                    r["free_text_chars"]))
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


def fetch_candidates():
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
    """{labeler: label count} for an openFDA search."""
    page = get({"search": search, "count": "openfda.manufacturer_name.exact", "limit": 1000})
    return {b["term"]: b["count"] for b in page["results"]} if page else {}


def scope(generic, route):
    search = RX + " AND openfda.generic_name.exact:" + quote(generic)
    return search + (" AND openfda.route.exact:" + quote(route) if route else "")


def facts_for(generic, route):
    search = scope(generic, route)
    return {"boxed": labelers(search + " AND _exists_:boxed_warning"),
            "full_text": labelers(search + " AND _exists_:indications_and_usage")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="out")
    parser.add_argument("--candidates", help="JSON list of generic names to check for a boxed warning; "
                        "others count as unboxed (an earlier run found no boxed-warning majority for them). "
                        "Saves openFDA calls under the keyless limit of 1,000 a day.")
    args = parser.parse_args(argv)

    boxed_candidates = None
    if args.candidates:
        with open(args.candidates, encoding="utf-8") as f:
            boxed_candidates = set(json.load(f))

    rx_total = total(RX)
    rx_by_labeler = labelers(RX)
    records = [r for r in latest_per_set(fetch_candidates()) if is_candidate(r)]
    print("candidate records: %d of %d prescription labels" % (len(records), rx_total), file=sys.stderr)
    keys = sorted({(first(r, "generic_name"), first(r, "route")) for r in records
                   if first(r, "generic_name") and kind_of(first(r, "generic_name")) == "drug"
                   and text_status(r) == "no_text"})
    facts = {}
    for i, (generic, route) in enumerate(keys, 1):
        if boxed_candidates is not None and generic not in boxed_candidates:
            facts[fact_key(generic, route)] = {"boxed": {}, "full_text": None}
        else:
            facts[fact_key(generic, route)] = facts_for(generic, route)
        if i % 25 == 0:
            print("generic-route pairs checked: %d/%d" % (i, len(keys)), file=sys.stderr)
    rows = [row_for(r, facts, {}) for r in records]
    apps = sorted({r["application"] for r in rows if r["boxed"] == "yes" and r["application"]})
    app_text = {a: sorted(labelers(RX + " AND openfda.application_number.exact:" + quote(a)
                                   + " AND _exists_:indications_and_usage")) for a in apps}
    rows = [row_for(r, facts, app_text) for r in records]
    meta = {"run_date": dt.date.today().isoformat(), "source": API, "query": HOLLOW, "text_min": TEXT_MIN,
            "boxed_share": BOXED_SHARE,
            "note": "Research data, not medical advice. openFDA says its data are unvalidated."}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "facts.json"), "w", encoding="utf-8") as f:
        json.dump({"facts": facts, "applications": app_text}, f, indent=1, sort_keys=True)
    print(write(rows, summarise(rows, rx_total, rx_by_labeler), args.out, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
