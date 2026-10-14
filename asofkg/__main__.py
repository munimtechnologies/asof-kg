"""Command line: python -m asofkg {demo,labels,check,ttl} [--known-at YYYY-MM-DD] [--view public|sponsor]"""

import argparse
import datetime as dt
import sys

from .kg import GuidelineKG, audit, load_encounters
from .rdf import to_turtle, versions_to_turtle
from .versions import VIEWS, label_audit, load_case_definitions, load_fills, load_labels


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


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="asofkg",
        description="Hindsight-free reasoning over guideline, drug-label and case-definition versions.")
    parser.add_argument("command", choices=("demo", "labels", "check", "ttl"),
                        help="demo: synthetic care-gap audit; labels: synthetic boxed-warning audit; "
                             "check: consistency report; ttl: the graph as Turtle")
    parser.add_argument("--known-at", default=None,
                        help="evaluation date YYYY-MM-DD (demo and labels default: today; ttl default: everything)")
    parser.add_argument("--view", default="public", choices=VIEWS,
                        help="whose knowledge counts: the public, or the regulator and sponsor")
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

    known_at = args.known_at or dt.date.today().isoformat()
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
