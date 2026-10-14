"""Look up every hollow prescription label's NDCs on DailyMed.

hollow_spl.py finds prescription labels with no prescribing text. People reach
a label through the NDC printed on the bottle or carton, so for each product
NDC of each hollow drug label this script asks DailyMed which SPLs it lists for
that NDC. An NDC is a dead end when every SPL DailyMed returns for it is
hollow: whoever looks it up finds no indications, no dosing and no boxed
warning. It also notes whether the NDC is in FDA's NDC Directory, with its
marketing dates (openFDA bulk download).

Research data, not medical advice: a listed SPL says nothing about the paper
insert in the box. Standard library only.
Apache-2.0. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name.
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
NDC_URL = "https://download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip"
USER_AGENT = "asof-kg ndc-lookup/1 (MV2 of Munim, Inc.; munimversion2@gmail.com)"

COLUMNS = ("set_id", "manufacturer", "generic_name", "effective_time", "boxed", "product_ndc",
           "dailymed_set_ids", "status", "in_ndc_directory", "marketing_category", "marketing_start_date",
           "marketing_end_date", "listing_expiration_date")


def classify(found, hollow_ids):
    """'lookup_failed', 'not_found', 'dead_end' (every SPL DailyMed lists is hollow) or 'full_text_elsewhere'."""
    if found is None:
        return "lookup_failed"
    if not found:
        return "not_found"
    if all(s in hollow_ids for s in found):
        return "dead_end"
    return "full_text_elsewhere"


def hollow_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def targets(rows):
    """The hollow drug labels to look up, and the set ids of every hollow label."""
    hollow = [r for r in rows if r["text_status"] == "no_text"]
    return [r for r in hollow if r["kind"] == "drug"], {r["set_id"] for r in hollow}


def ndcs_of(label):
    return [n for n in label.get("product_ndcs", "").split("|") if n]


def ndc_index(products):
    """{product_ndc: product} from the openFDA NDC Directory's results list."""
    return {p["product_ndc"]: p for p in products if p.get("product_ndc")}


def load_ndc_directory(folder):
    """The openFDA NDC Directory bulk file (zipped or not) found in ``folder``; [] if none."""
    for path in sorted(glob.glob(os.path.join(folder, "**", "*ndc*.json*"), recursive=True)):
        if path.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                name = next(n for n in z.namelist() if n.endswith(".json"))
                return json.loads(z.read(name).decode("utf-8"))["results"]
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                return json.load(f)["results"]
    return []


def ensure_ndc_directory(folder):
    """Download the NDC Directory into ``folder`` unless a copy is already there."""
    os.makedirs(folder, exist_ok=True)
    have = [p for p in glob.glob(os.path.join(folder, "**", "*ndc*.json*"), recursive=True)
            if p.endswith((".zip", ".json"))]
    if not have:
        path = os.path.join(folder, os.path.basename(NDC_URL))
        request = urllib.request.Request(NDC_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=600) as response, open(path + ".part", "wb") as f:
            shutil.copyfileobj(response, f)
        os.replace(path + ".part", path)
    return folder


def marketed(row, today):
    """In the NDC Directory with no marketing end date before ``today`` (YYYYMMDD)."""
    return row["in_ndc_directory"] == "yes" and (not row["marketing_end_date"] or row["marketing_end_date"] >= today)


def rows_for(label, lookups, index, hollow_ids):
    """One row per product NDC of a hollow label (one 'no_ndc' row if openFDA lists none)."""
    out = []
    for ndc in ndcs_of(label) or [""]:
        found = lookups.get(ndc) if ndc else []
        product = index.get(ndc, {})
        out.append({
            "set_id": label["set_id"],
            "manufacturer": label["manufacturer"],
            "generic_name": label["generic_name"],
            "effective_time": label["effective_time"],
            "boxed": label.get("boxed", ""),
            "product_ndc": ndc,
            "dailymed_set_ids": "|".join(found or []),
            "status": classify(found, hollow_ids) if ndc else "no_ndc",
            "in_ndc_directory": ("yes" if product else "no") if index else "",
            "marketing_category": product.get("marketing_category", ""),
            "marketing_start_date": product.get("marketing_start_date", ""),
            "marketing_end_date": product.get("marketing_end_date", ""),
            "listing_expiration_date": product.get("listing_expiration_date", ""),
        })
    return out


def summarise(rows, today):
    labels, by_status = {}, {}
    for r in rows:
        labels.setdefault(r["set_id"], []).append(r)
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    dead = {s: rs for s, rs in labels.items() if all(r["status"] == "dead_end" for r in rs)}
    by_labeler = {}
    for rs in dead.values():
        by_labeler[rs[0]["manufacturer"]] = by_labeler.get(rs[0]["manufacturer"], 0) + 1
    dead_ndcs = [r for r in rows if r["status"] == "dead_end"]
    return {
        "labels": len(labels),
        "product_ndcs": len(rows),
        "ndcs_by_status": dict(sorted(by_status.items())),
        "labels_whose_every_ndc_is_a_dead_end": len(dead),
        "dead_end_labels_by_labeler": dict(sorted(by_labeler.items(), key=lambda kv: (-kv[1], kv[0]))),
        "boxed_labels_whose_every_ndc_is_a_dead_end": sum(1 for rs in dead.values() if rs[0]["boxed"] == "yes"),
        "dead_end_ndcs_in_ndc_directory": sum(1 for r in dead_ndcs if r["in_ndc_directory"] == "yes"),
        "dead_end_ndcs_marketed": sum(1 for r in dead_ndcs if marketed(r, today)),
        "boxed_dead_end_set_ids": sorted(s for s, rs in dead.items() if rs[0]["boxed"] == "yes"),
    }


def write(rows, summary, out, meta):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ndc.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": summary}, f, indent=2)
    s = summary
    lines = ["# DailyMed NDC lookups for prescription labels with no prescribing text (%s)" % meta["run_date"], "",
             "- Hollow drug labels looked up: %d" % s["labels"],
             "- Product NDCs: %d (%s)" % (s["product_ndcs"],
                                          ", ".join("%s %d" % kv for kv in s["ndcs_by_status"].items())),
             "- Labels whose every NDC leads only to hollow labels on DailyMed: %d"
             % s["labels_whose_every_ndc_is_a_dead_end"],
             "- ... of them for a drug whose labels mostly carry a boxed warning: %d"
             % s["boxed_labels_whose_every_ndc_is_a_dead_end"],
             "- Dead-end NDCs in FDA's NDC Directory: %d, of which still marketed on %s: %d"
             % (s["dead_end_ndcs_in_ndc_directory"], meta["today"], s["dead_end_ndcs_marketed"])]
    if meta.get("note"):
        lines.append("- Note: " + meta["note"])
    lines += ["", "## Dead-end labels by labeler", "", "| Labeler | Labels |", "|---|---|"]
    for name, n in s["dead_end_labels_by_labeler"].items():
        lines.append("| %s | %d |" % (name, n))
    lines += ["", "## Boxed-warning drugs whose NDCs lead only to a hollow label", "",
              "| Generic | Labeler | Set id | NDCs |", "|---|---|---|---|"]
    boxed = set(s["boxed_dead_end_set_ids"])
    seen = {}
    for r in rows:
        if r["set_id"] in boxed:
            seen.setdefault(r["set_id"], []).append(r)
    for set_id, rs in sorted(seen.items(), key=lambda kv: (kv[1][0]["generic_name"], kv[0])):
        lines.append("| %s | %s | %s | %s |" % (rs[0]["generic_name"], rs[0]["manufacturer"], set_id,
                                                ", ".join(r["product_ndc"] for r in rs)))
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def dailymed_set_ids(ndc, pause=0.25, tries=5):
    """Set ids of every SPL DailyMed lists for a product NDC; None if DailyMed could not be reached."""
    url = DAILYMED + "?" + urllib.parse.urlencode({"ndc": ndc})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                page = json.loads(response.read().decode("utf-8"))
            time.sleep(pause)
            return sorted({d["setid"] for d in page.get("data", []) if d.get("setid")})
        except (urllib.error.URLError, ValueError):
            time.sleep(5 * (attempt + 1))
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--hollow", required=True, help="hollow.csv written by hollow_spl.py 2.1 or later")
    parser.add_argument("--data-dir", default="data", help="where the NDC Directory bulk file is kept")
    parser.add_argument("--out", default="out")
    args = parser.parse_args(argv)

    labels, hollow_ids = targets(hollow_rows(args.hollow))
    ndcs = sorted({n for label in labels for n in ndcs_of(label)})
    lookups = {}
    for i, ndc in enumerate(ndcs, 1):
        lookups[ndc] = dailymed_set_ids(ndc)
        if i % 50 == 0:
            print("NDCs looked up: %d/%d" % (i, len(ndcs)), file=sys.stderr)
    note = ""
    try:
        index = ndc_index(load_ndc_directory(ensure_ndc_directory(args.data_dir)))
    except Exception as e:  # the DailyMed lookups still stand without it
        index, note = {}, "NDC Directory unavailable (%s)" % e
    today = dt.date.today()
    rows = [row for label in labels for row in rows_for(label, lookups, index, hollow_ids)]
    meta = {"run_date": today.isoformat(), "today": today.strftime("%Y%m%d"), "source": DAILYMED,
            "ndc_directory": NDC_URL if index else "", "note": note,
            "disclaimer": "Research data, not medical advice. openFDA says its data are unvalidated."}
    print(write(rows, summarise(rows, meta["today"]), args.out, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
