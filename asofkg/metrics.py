"""How often a graph without time answers differently, and how often it uses later knowledge.

These are the measures behind the "no hindsight" claim. A query asks which
version of a subject (a guideline topic, a drug's label, a condition's case
definition) was in force on a day. The hindsight-free answer uses only what
was known that day. The static answer is the newest version, which a graph
built today without time gives for every day. Over a grid of days:

- ``changed``: queries where the two answers differ.
- ``leaked``: queries where the static answer rests on a version that could
  not yet be known that day.
- ``hindsight``: queries where the hindsight-free answer rests on a version
  not yet known. It must be 0, and the tests check that it is.

Days before a subject's first version are skipped, so days before a drug was
approved or a guideline existed do not inflate the rates.
"""

import datetime as dt

from .instants import as_date

COMPARISONS = ("version", "value")


def yearly(first_year, last_year):
    """January 1 of each year from ``first_year`` to ``last_year``, inclusive."""
    return [dt.date(year, 1, 1) for year in range(first_year, last_year + 1)]


def guideline_points(kg, days):
    """One query per guideline topic and day, with its hindsight-free and static answers."""
    rows = []
    for topic in kg.topics():
        versions = [v for v in kg.versions if v.topic == topic]
        first = min(v.published.latest for v in versions)
        newest = max(versions, key=lambda v: v.published.latest)
        for day in days:
            day = as_date(day)
            if day < first:
                continue
            then = kg.in_force(topic, day, day)
            rows.append({"subject": topic, "day": day,
                         "then": None if then is None else then.id, "static": newest.id,
                         "then_known": then is None or then.known_by(day),
                         "static_known": newest.known_by(day)})
    return rows


def version_points(chains, days, view="public", fact=None):
    """One query per subject and day for label or case-definition versions.

    With ``fact`` (such as "boxed_warning") each row also carries that fact
    from both answers, so answers can be compared by what they say: two
    versions may say the same thing.
    """
    rows = []
    for subject in chains.subjects():
        versions = [v for v in chains.versions if v.subject == subject]
        first = min(v.effective.latest for v in versions)
        newest = chains.latest(subject)
        for day in days:
            day = as_date(day)
            if day < first:
                continue
            then = chains.in_force(subject, day, day, view)
            row = {"subject": subject, "day": day,
                   "then": None if then is None else then.id, "static": newest.id,
                   "then_known": then is None or then.known_by(day, view),
                   "static_known": newest.known_by(day, view)}
            if fact is not None:
                row["then_value"] = None if then is None else then.facts.get(fact)
                row["static_value"] = newest.facts.get(fact)
            rows.append(row)
    return rows


def summarize(rows, by="version"):
    """Counts and rates for query rows.

    ``by="version"`` compares which version answers; ``by="value"`` compares
    the fact passed to ``version_points``.
    """
    if by not in COMPARISONS:
        raise ValueError("unknown comparison %r" % (by,))
    then, static = ("then", "static") if by == "version" else ("then_value", "static_value")
    queries = len(rows)
    changed = sum(1 for r in rows if r[then] != r[static])
    leaked = sum(1 for r in rows if not r["static_known"])
    hindsight = sum(1 for r in rows if not r["then_known"])
    return {"queries": queries, "changed": changed, "leaked": leaked, "hindsight": hindsight,
            "changed_rate": changed / queries if queries else 0.0,
            "leaked_rate": leaked / queries if queries else 0.0}


def evidence_lag(labels):
    """Days from evidence to label change, for label versions that cite evidence.

    ``evidence_first_public`` is when the trial report behind a change first
    appeared in a journal; ``signal_first_public`` is FDA's first public
    notice of the safety signal. A negative lag means the label changed
    before the journal article appeared.
    """
    rows = []
    for v in labels.versions:
        evidence = v.facts.get("evidence_first_public")
        signal = v.facts.get("signal_first_public")
        if evidence is None and signal is None:
            continue
        effective = v.effective.latest
        evidence = None if evidence is None else as_date(evidence)
        signal = None if signal is None else as_date(signal)
        rows.append({"id": v.id, "drug": v.subject, "effective": effective,
                     "evidence_pmid": v.facts.get("evidence_pmid"),
                     "evidence_first_public": evidence,
                     "evidence_lag_days": None if evidence is None else (effective - evidence).days,
                     "signal_first_public": signal,
                     "signal_lag_days": None if signal is None else (effective - signal).days})
    return rows
