"""Command line: python -m asofkg {demo,labels,metrics,check,ttl,kgx} [--known-at YYYY-MM-DD] [--view public|sponsor] [--out DIR]"""

import argparse
import datetime as dt
import sys

from .instants import as_date
from .kg import GuidelineKG, audit, load_encounters
from .kgx import to_kgx, write_kgx
from .metrics import evidence_lag, guideline_points, summarize, version_points, yearly
from .rdf import to_turtle, versions_to_turtle
from .versions import VIEWS, label_audit, load_case_definitions, load_fills, load_labels

FIRST_YEAR = 2000  # first year of the metrics grid


def _cell(v):
    if v["grade"]:
        return "%s (grade %s, %s)" % (v["verdict"], v["grade"], v["version"])
    if v["version"]:
        return "%s (%s)" % (v["verdict"], v["version"])
    return v["verdict"]


def _box(risks):
    if risks is None:
        return "unknown"
    return "; ".join(risks) if risks else "none"


def _count(n, total):
    return "%d (%d%%)" % (n, round(100.0 * n / total)) if total else "0"


def _since(day, lag):
    if day is None:
        return "n/a"
    if lag >= 0:
        return "%s (%d days before)" % (day.isoformat(), lag)
    return "%s (%d days after)" % (day.isoformat(), -lag)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="asofkg",
        description="Hindsight-free reasoning over guideline, drug-label and case-definition versions.")
    parser.add_argument("command", choices=("demo", "labels", "metrics", "check", "ttl", "kgx"),
                        help="demo: synthetic care-gap audit; labels: synthetic boxed-warning audit; "
                             "metrics: how often a graph without time answers differently or uses later "
                             "knowledge; check: consistency report; ttl: the graph as Turtle; "
                             "kgx: the graph as KGX nodes.tsv and edges.tsv (Biolink)")
    parser.add_argument("--known-at", default=None,
                        help="evaluation date YYYY-MM-DD (demo, labels and metrics default: today; "
                             "ttl and kgx default: everything)")
    parser.add_argument("--view", default="public", choices=VIEWS,
                        help="whose knowledge counts: the public, or the regulator and sponsor")
    parser.add_argument("--out", default="kgx", help="kgx: directory to write the two files to (default: kgx)")
    args = parser.parse_args(argv)
    kg = GuidelineKG.load()
    labels = load_labels()
    casedefs = load_case_definitions()

    if args.command == "check":
        problems = kg.check() + labels.check() + casedefs.check()
        for p in problems:
            print(p)
        print("%d problem(s)" % len(problems))
        return 1 if problems else 0

    if args.command == "ttl":
        sys.stdout.write(to_turtle(kg, args.known_at))
        sys.stdout.write("\n")
        sys.stdout.write(versions_to_turtle(labels, args.known_at, args.view, prefixes=False))
        sys.stdout.write("\n")
        sys.stdout.write(versions_to_turtle(casedefs, args.known_at, args.view, prefixes=False))
        return 0

    if args.command == "kgx":
        nodes, edges = to_kgx(kg, labels, casedefs, args.known_at, args.view)
        node_path, edge_path = write_kgx(nodes, edges, args.out)
        print("%d nodes -> %s" % (len(nodes), node_path))
        print("%d edges -> %s" % (len(edges), edge_path))
        return 0

    known_at = args.known_at or dt.date.today().isoformat()
    if args.command == "metrics":
        last_year = as_date(known_at).year
        days = yearly(FIRST_YEAR, last_year)
        guide = guideline_points(kg, days)
        label_rows = version_points(labels, days, args.view, fact="boxed_warning")
        case_rows = version_points(casedefs, days, args.view)
        table = [("guidelines (USPSTF)", summarize(guide)),
                 ("drug labels: version", summarize(label_rows)),
                 ("drug labels: boxed warning", summarize(label_rows, by="value")),
                 ("case definitions (CDC)", summarize(case_rows)),
                 ("all three, by version", summarize(guide + label_rows + case_rows))]
        print("Newest version only vs hindsight-free answers, on January 1 of %d-%d (%s view)"
              % (FIRST_YEAR, last_year, args.view))
        print("%-28s %7s %15s %15s %9s" % ("domain", "queries", "answer changes", "later knowledge", "hindsight"))
        for name, s in table:
            print("%-28s %7d %15s %15s %9d" % (name, s["queries"], _count(s["changed"], s["queries"]),
                                               _count(s["leaked"], s["queries"]), s["hindsight"]))
        print("\nEvidence and label changes (days from each to the label change)")
        for r in evidence_lag(labels):
            print("%-18s label changed %s; trial report %s; FDA signal notice %s" % (
                r["id"], r["effective"].isoformat(), _since(r["evidence_first_public"], r["evidence_lag_days"]),
                _since(r["signal_first_public"], r["signal_lag_days"])))
        return 0

    if args.command == "labels":
        rows = label_audit(labels, load_fills(), known_at, args.view)
        print("Synthetic boxed-warning audit, evaluated on %s (made-up fills, not real people)" % known_at)
        for r in rows:
            print("%s %s %s%s" % (r["id"], r["date"], r["drug"], "" if r["agree"] else "   <- differs"))
            print("    on the label that day:  %s (%s)" % (_box(r["then"]), r["then_version"]))
            if r["announced"]:
                print("    announced, not yet on the label: %s" % ", ".join(r["announced"]))
            print("    newest label only:      %s (%s)" % (_box(r["static"]), r["static_version"]))
        differ = sum(1 for r in rows if not r["agree"])
        print("\n%d of %d boxed-warning answers change when time is ignored." % (differ, len(rows)))
        return 0

    rows = audit(kg, load_encounters(), known_at)
    print("Synthetic care-gap audit, evaluated on %s (made-up encounters, not real people)" % known_at)
    print("%-3s %-10s %-31s %-31s %s" % ("id", "date", "topic", "version in force then", "newest version only"))
    for r in rows:
        print("%-3s %-10s %-31s %-31s %s%s" % (
            r["id"], r["date"], r["topic"], _cell(r["temporal"]), _cell(r["static"]),
            "" if r["agree"] else "   <- differs"))
    differ = sum(1 for r in rows if not r["agree"])
    print("\n%d of %d verdicts change when time is ignored." % (differ, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
