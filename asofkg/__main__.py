"""Command line: python -m asofkg {demo,check,ttl} [--known-at YYYY-MM-DD]"""

import argparse
import datetime as dt
import sys

from .kg import GuidelineKG, audit, load_encounters
from .rdf import to_turtle


def _cell(v):
    if v["grade"]:
        return "%s (grade %s, %s)" % (v["verdict"], v["grade"], v["version"])
    if v["version"]:
        return "%s (%s)" % (v["verdict"], v["version"])
    return v["verdict"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="asofkg",
        description="Hindsight-free reasoning over USPSTF guideline versions.")
    parser.add_argument("command", choices=("demo", "check", "ttl"),
                        help="demo: synthetic care-gap audit; check: consistency report; "
                             "ttl: the graph as Turtle")
    parser.add_argument("--known-at", default=None,
                        help="evaluation date YYYY-MM-DD (demo default: today; ttl default: everything)")
    args = parser.parse_args(argv)
    kg = GuidelineKG.load()

    if args.command == "check":
        problems = kg.check()
        for p in problems:
            print(p)
        print("%d problem(s)" % len(problems))
        return 1 if problems else 0

    if args.command == "ttl":
        sys.stdout.write(to_turtle(kg, args.known_at))
        return 0

    known_at = args.known_at or dt.date.today().isoformat()
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
