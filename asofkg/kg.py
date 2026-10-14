"""Guideline versions, the recommendations in them, and as-of queries over both."""

import json
import os

from .instants import Instant, as_date

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GUIDELINES = os.path.join(DATA_DIR, "uspstf.json")
ENCOUNTERS = os.path.join(DATA_DIR, "synthetic_encounters.json")

GRADES = ("A", "B", "C", "D", "I")
ROUTINE = ("A", "B")  # grades the USPSTF asks clinicians to offer or provide
AGAINST = ("D",)  # grades that recommend against the service
SEXES = ("female", "male")
OLDEST = 150  # stands in for "no upper age" when comparing age bands


class Recommendation:
    """One graded recommendation for one population inside a guideline version."""

    def __init__(self, version, raw):
        self.version = version
        self.grade = raw["grade"]
        self.sex = raw.get("sex")
        self.age_min = raw.get("age_min")
        self.age_max = raw.get("age_max")
        self.min_cvd_risk_10y = raw.get("min_cvd_risk_10y")
        self.condition = raw.get("condition")
        self.quote = raw.get("quote")

    def covers(self, age, sex=None, cvd_risk_10y=None):
        """True if a person of this age, sex and 10-year CVD risk is in the population."""
        if self.sex is not None and sex != self.sex:
            return False
        if self.age_min is not None and age < self.age_min:
            return False
        if self.age_max is not None and age > self.age_max:
            return False
        if self.min_cvd_risk_10y is not None:
            if cvd_risk_10y is None or cvd_risk_10y < self.min_cvd_risk_10y:
                return False
        return True

    def population(self):
        """A short label such as 'female, 40-74'."""
        if self.age_min is None and self.age_max is None:
            ages = "all ages"
        elif self.age_max is None:
            ages = "%d+" % self.age_min
        elif self.age_min is None:
            ages = "under %d" % (self.age_max + 1)
        else:
            ages = "%d-%d" % (self.age_min, self.age_max)
        parts = [self.sex, ages] if self.sex else [ages]
        if self.min_cvd_risk_10y is not None:
            parts.append("10-year CVD risk >= %d%%" % round(self.min_cvd_risk_10y * 100))
        return ", ".join(parts)


class GuidelineVersion:
    """One published version of a guideline on a topic."""

    def __init__(self, raw):
        self.id = raw["id"]
        self.topic = raw["topic"]
        self.title = raw["title"]
        self.pmid = raw["pmid"]
        self.journal = raw["journal"]
        self.published = Instant(raw["published"])
        self.supersedes = raw.get("supersedes")
        self.recommendations = [Recommendation(self, r) for r in raw["recommendations"]]

    def known_by(self, day):
        """True if this version had certainly been published by ``day``."""
        return self.published.certainly_by(day)

    def __repr__(self):
        return "GuidelineVersion(%r)" % self.id


def _overlaps(a, b):
    if a.sex is not None and b.sex is not None and a.sex != b.sex:
        return False
    lo = max(a.age_min or 0, b.age_min or 0)
    hi = min(OLDEST if a.age_max is None else a.age_max,
             OLDEST if b.age_max is None else b.age_max)
    return lo <= hi


class GuidelineKG:
    """Guideline versions linked by supersession, queried as of a date.

    Two times are kept apart. *Valid time* is when a version was in force.
    *Knowledge time* is when a fact could be known: a version is known from
    its publication, and the end of its time in force is known only once a
    successor has been published. Every query takes a ``known_at`` date and
    uses nothing published after it.
    """

    def __init__(self, versions, topics=None):
        self.versions = list(versions)
        self.by_id = {v.id: v for v in self.versions}
        self.topic_info = dict(topics or {})

    @classmethod
    def load(cls, path=GUIDELINES):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return cls([GuidelineVersion(g) for g in raw["guidelines"]], raw.get("topics"))

    def topics(self):
        return sorted({v.topic for v in self.versions})

    def in_force(self, topic, on, known_at=None):
        """The version of ``topic`` in force on ``on``, judged from what was published by ``known_at``.

        ``known_at`` defaults to ``on``. A version published after
        ``known_at`` is invisible even if it would apply on ``on``. Returns
        None when no version of the topic is known.
        """
        on = as_date(on)
        cutoff = on if known_at is None else min(on, as_date(known_at))
        live = [v for v in self.versions if v.topic == topic and v.known_by(cutoff)]
        replaced = {v.supersedes for v in live}
        heads = [v for v in live if v.id not in replaced]
        if not heads:
            return None
        return max(heads, key=lambda v: v.published.latest)

    def interval(self, version_id, known_at):
        """When a version was in force, as could be known on ``known_at``.

        Returns (start, end) dates with ``end`` exclusive, or None if the
        version was not yet published. ``end`` stays None until a successor
        has been published: before that, nobody could know the version would
        be replaced.
        """
        version = self.by_id[version_id]
        known_at = as_date(known_at)
        if not version.known_by(known_at):
            return None
        ends = [w.published.latest for w in self.versions
                if w.supersedes == version.id and w.known_by(known_at)]
        return version.published.latest, (min(ends) if ends else None)

    def recommendation(self, topic, on, age, sex=None, cvd_risk_10y=None, known_at=None):
        """The recommendation covering a person on a date, and the version it came from.

        Returns (None, None) when no version of the topic is known, and
        (None, version) when the version in force says nothing for this person.
        """
        version = self.in_force(topic, on, known_at)
        if version is None:
            return None, None
        for rec in version.recommendations:
            if rec.covers(age, sex, cvd_risk_10y):
                return rec, version
        return None, version

    def check(self):
        """Consistency problems in the graph, as a list of messages (empty when clean)."""
        problems = []
        seen = set()
        for v in self.versions:
            if v.id in seen:
                problems.append("duplicate id %s" % v.id)
            seen.add(v.id)

        for v in self.versions:
            if v.supersedes is None:
                continue
            old = self.by_id.get(v.supersedes)
            if old is None:
                problems.append("%s supersedes unknown %s" % (v.id, v.supersedes))
                continue
            if old.topic != v.topic:
                problems.append("%s supersedes %s from another topic" % (v.id, old.id))
            if not old.published.latest < v.published.earliest:
                problems.append("%s is not published after %s" % (v.id, old.id))

        for v in self.versions:
            walked, current = set(), v
            while current is not None and current.supersedes is not None:
                if current.id in walked:
                    problems.append("supersession cycle through %s" % v.id)
                    break
                walked.add(current.id)
                current = self.by_id.get(current.supersedes)

        for topic in self.topics():
            versions = [v for v in self.versions if v.topic == topic]
            replaced = [v.supersedes for v in versions if v.supersedes is not None]
            heads = [v for v in versions if v.id not in replaced]
            if len(heads) != 1:
                problems.append("topic %s has %d latest versions, not 1" % (topic, len(heads)))
            if len(set(replaced)) != len(replaced):
                problems.append("topic %s branches: two versions supersede the same one" % topic)

        for v in self.versions:
            for rec in v.recommendations:
                if rec.grade not in GRADES:
                    problems.append("%s has unknown grade %r" % (v.id, rec.grade))
                if rec.sex is not None and rec.sex not in SEXES:
                    problems.append("%s has unknown sex %r" % (v.id, rec.sex))
                if rec.age_min is not None and rec.age_max is not None and rec.age_min > rec.age_max:
                    problems.append("%s has an empty age band %d-%d" % (v.id, rec.age_min, rec.age_max))
            recs = v.recommendations
            for i, a in enumerate(recs):
                for b in recs[i + 1:]:
                    if _overlaps(a, b):
                        problems.append("%s has overlapping recommendations (%s and %s)" % (v.id, a.grade, b.grade))
        return problems


def load_encounters(path=ENCOUNTERS):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["encounters"]


def verdict(kg, encounter, on, known_at):
    """Judge one encounter against the version in force on ``on`` as known on ``known_at``."""
    rec, version = kg.recommendation(encounter["topic"], on, encounter["age"], encounter.get("sex"),
                                     encounter.get("cvd_risk_10y"), known_at)
    if version is None:
        return {"verdict": "unknown", "grade": None, "version": None}
    if rec is None:
        return {"verdict": "no recommendation", "grade": None, "version": version.id}
    if rec.grade in ROUTINE and not encounter["done"]:
        result = "gap"
    elif rec.grade in AGAINST and encounter["done"]:
        result = "against"
    else:
        result = "ok"
    return {"verdict": result, "grade": rec.grade, "version": version.id}


def audit(kg, encounters, known_at):
    """Compare a hindsight-free care-gap audit with a static one.

    The temporal audit judges each encounter by the version in force on its
    date. The static audit judges every encounter by the newest version known
    on ``known_at``, as a knowledge graph without time would.
    """
    rows = []
    for e in encounters:
        temporal = verdict(kg, e, e["date"], e["date"])
        static = verdict(kg, e, known_at, known_at)
        rows.append({"id": e["id"], "date": e["date"], "topic": e["topic"],
                     "temporal": temporal, "static": static,
                     "agree": temporal["verdict"] == static["verdict"]})
    return rows
