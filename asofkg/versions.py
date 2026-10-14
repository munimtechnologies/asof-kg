"""Versioned records whose effective date and first public date differ.

Drug labels and surveillance case definitions change by versions that are
known on one day and take effect on another. FDA writes to a drug's sponsor
about a required safety change, often announces it, and approves the new
label weeks later. CSTE adopts a case definition in one year and it is used
from the next. So each version carries up to three dates:

- ``effective``: when it took effect (valid time).
- ``announced``: when the public could first know it (knowledge time).
- ``notified``: when the regulator and the sponsor knew it, if earlier.

Queries take an ``on`` date (valid time), a ``known_at`` date (knowledge
time) and a ``view``: "public", or "sponsor" for what the regulator and the
product's sponsor knew.
"""

import json
import os

from .instants import Instant, as_date

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LABELS = os.path.join(DATA_DIR, "fda_boxed_warnings.json")
CASE_DEFINITIONS = os.path.join(DATA_DIR, "cdc_case_definitions.json")
FILLS = os.path.join(DATA_DIR, "synthetic_fills.json")

VIEWS = ("public", "sponsor")


class Version:
    """One version of a drug label, case definition or similar record."""

    def __init__(self, raw):
        self.id = raw["id"]
        self.subject = raw["subject"]
        self.title = raw.get("title", raw["id"])
        self.effective = Instant(raw["effective"])
        self.announced = Instant(raw.get("announced") or raw["effective"])
        self.notified = Instant(raw["notified"]) if raw.get("notified") else None
        self.supersedes = raw.get("supersedes")
        self.facts = dict(raw.get("facts", {}))
        self.sources = list(raw.get("sources", []))
        self.note = raw.get("note")

    def known_from(self, view="public"):
        """The instant from which this version could be known in ``view``."""
        if view not in VIEWS:
            raise ValueError("unknown view %r" % (view,))
        if view == "sponsor" and self.notified is not None and self.notified.latest < self.announced.latest:
            return self.notified
        return self.announced

    def known_by(self, day, view="public"):
        """True if this version could certainly be known by ``day`` in ``view``."""
        return self.known_from(view).certainly_by(day)

    def __repr__(self):
        return "Version(%r)" % self.id


class VersionChains:
    """Chains of versions, one chain per subject, queried in valid and knowledge time.

    Unlike guideline versions, a version here may be known before it takes
    effect, so the end of its predecessor's interval can be known ahead of
    time. A version that took effect before ``known_at`` but was announced
    after it is still invisible.
    """

    def __init__(self, versions, subjects=None, kind="Version"):
        self.versions = list(versions)
        self.by_id = {v.id: v for v in self.versions}
        self.subject_info = dict(subjects or {})
        self.kind = kind

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return cls([Version(v) for v in raw["versions"]], raw.get("subjects"), raw.get("kind", "Version"))

    def subjects(self):
        return sorted({v.subject for v in self.versions})

    def _known(self, subject, known_at, view):
        return [v for v in self.versions if v.subject == subject and v.known_by(known_at, view)]

    def in_force(self, subject, on, known_at=None, view="public"):
        """The version of ``subject`` in effect on ``on``, judged from what was known on ``known_at``.

        ``known_at`` defaults to ``on``. Returns None when no known version
        had taken effect by ``on``.
        """
        on = as_date(on)
        known_at = on if known_at is None else as_date(known_at)
        live = [v for v in self._known(subject, known_at, view) if v.effective.certainly_by(on)]
        replaced = {v.supersedes for v in live}
        heads = [v for v in live if v.id not in replaced]
        if not heads:
            return None
        return max(heads, key=lambda v: v.effective.latest)

    def pending(self, subject, known_at, view="public"):
        """Versions known on ``known_at`` that had not yet taken effect, soonest first."""
        known_at = as_date(known_at)
        waiting = [v for v in self._known(subject, known_at, view) if not v.effective.certainly_by(known_at)]
        return sorted(waiting, key=lambda v: v.effective.latest)

    def latest(self, subject, known_at=None, view="public"):
        """The newest version of ``subject`` known on ``known_at`` (default: any), as a static graph would hold it."""
        versions = [v for v in self.versions if v.subject == subject
                    and (known_at is None or v.known_by(known_at, view))]
        if not versions:
            return None
        return max(versions, key=lambda v: v.effective.latest)

    def interval(self, version_id, known_at, view="public"):
        """When a version was in effect, as could be known on ``known_at``.

        Returns (start, end) dates with ``end`` exclusive, or None if the
        version was not yet known. ``end`` stays None until a successor is
        known; it may lie after ``known_at`` when the successor was
        announced before taking effect.
        """
        version = self.by_id[version_id]
        known_at = as_date(known_at)
        if not version.known_by(known_at, view):
            return None
        ends = [w.effective.latest for w in self.versions
                if w.supersedes == version.id and w.known_by(known_at, view)]
        return version.effective.latest, (min(ends) if ends else None)

    def check(self):
        """Consistency problems, as a list of messages (empty when clean)."""
        problems = []
        seen = set()
        for v in self.versions:
            if v.id in seen:
                problems.append("duplicate id %s" % v.id)
            seen.add(v.id)
            if v.notified is not None and v.notified.earliest > v.announced.latest:
                problems.append("%s was notified after it was announced" % v.id)

        for v in self.versions:
            if v.supersedes is None:
                continue
            old = self.by_id.get(v.supersedes)
            if old is None:
                problems.append("%s supersedes unknown %s" % (v.id, v.supersedes))
                continue
            if old.subject != v.subject:
                problems.append("%s supersedes %s from another subject" % (v.id, old.id))
            if not old.effective.latest < v.effective.earliest:
                problems.append("%s does not take effect after %s" % (v.id, old.id))

        for v in self.versions:
            walked, current = set(), v
            while current is not None and current.supersedes is not None:
                if current.id in walked:
                    problems.append("supersession cycle through %s" % v.id)
                    break
                walked.add(current.id)
                current = self.by_id.get(current.supersedes)

        for subject in self.subjects():
            versions = [v for v in self.versions if v.subject == subject]
            replaced = [v.supersedes for v in versions if v.supersedes is not None]
            heads = [v for v in versions if v.id not in replaced]
            if len(heads) != 1:
                problems.append("subject %s has %d latest versions, not 1" % (subject, len(heads)))
            if len(set(replaced)) != len(replaced):
                problems.append("subject %s branches: two versions supersede the same one" % subject)
        return problems


def load_labels(path=LABELS):
    return VersionChains.load(path)


def load_case_definitions(path=CASE_DEFINITIONS):
    return VersionChains.load(path)


def load_fills(path=FILLS):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["fills"]


def boxed_warning(labels, drug, on, known_at=None, view="public"):
    """The risks in a drug's boxed warning on ``on``: a list, empty if it had none.

    Returns None when no label version of the drug is known.
    """
    version = labels.in_force(drug, on, known_at, view)
    if version is None:
        return None
    return list(version.facts.get("boxed_warning", []))


def check_copy(labels, drug, copy_date, copy_has_box, view="public"):
    """Check a copy of a drug label, dated ``copy_date``, against the version in effect that day.

    A copy that shows a boxed warning when the label then in effect had
    none (or the reverse) is stale. ``older`` lists the earlier versions
    the copy agrees with.
    """
    expected = labels.in_force(drug, copy_date, None, view)
    if expected is None:
        return {"expected": None, "consistent": None, "older": []}
    has_box = bool(expected.facts.get("boxed_warning"))
    older = [v.id for v in labels.versions
             if v.subject == drug and v.effective.latest < expected.effective.latest
             and bool(v.facts.get("boxed_warning")) == bool(copy_has_box)]
    return {"expected": expected.id, "consistent": has_box == bool(copy_has_box), "older": older}


def label_audit(labels, fills, known_at, view="public"):
    """Compare what each label said on the fill date with the newest label only.

    For each fill the hindsight-free side gives the boxed warning in effect
    that day and any change already announced but not yet on the label. The
    static side gives the boxed warning of the newest version known on
    ``known_at``, as a graph without time would.
    """
    rows = []
    for fill in fills:
        then = labels.in_force(fill["drug"], fill["date"], fill["date"], view)
        coming = labels.pending(fill["drug"], fill["date"], view)
        newest = labels.latest(fill["drug"], known_at, view)
        then_box = None if then is None else list(then.facts.get("boxed_warning", []))
        newest_box = None if newest is None else list(newest.facts.get("boxed_warning", []))
        rows.append({"id": fill["id"], "date": fill["date"], "drug": fill["drug"],
                     "then": then_box, "then_version": None if then is None else then.id,
                     "announced": [v.id for v in coming],
                     "static": newest_box, "static_version": None if newest is None else newest.id,
                     "agree": then_box == newest_box})
    return rows
