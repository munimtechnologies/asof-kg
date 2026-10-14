"""Dates known to day, month or year precision, and Allen's interval relations."""

import calendar
import datetime as dt


def as_date(value):
    """A datetime.date from a date, a datetime or an ISO 'YYYY-MM-DD' string."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


class Instant:
    """A calendar date known to day, month or year precision.

    It is held as the earliest and latest day it could be. Whether something
    was known by a day is decided on the latest day, so a date given only as
    a year never counts as known before that year is over. That keeps answers
    free of hindsight when sources give coarse dates.
    """

    __slots__ = ("text", "earliest", "latest")

    def __init__(self, text):
        text = str(text).strip()
        parts = text.split("-")
        if not 1 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
            raise ValueError("not an ISO date: %r" % (text,))
        year = int(parts[0])
        if len(parts) == 1:
            self.earliest = dt.date(year, 1, 1)
            self.latest = dt.date(year, 12, 31)
        elif len(parts) == 2:
            month = int(parts[1])
            self.earliest = dt.date(year, month, 1)
            self.latest = dt.date(year, month, calendar.monthrange(year, month)[1])
        else:
            self.earliest = self.latest = dt.date(year, int(parts[1]), int(parts[2]))
        self.text = text

    @property
    def precision(self):
        return ("year", "month", "day")[self.text.count("-")]

    def certainly_by(self, day):
        """True only if this instant is on or before ``day`` whatever its exact day."""
        return self.latest <= as_date(day)

    def possibly_by(self, day):
        """True if this instant could be on or before ``day``."""
        return self.earliest <= as_date(day)

    def __eq__(self, other):
        return isinstance(other, Instant) and self.text == other.text

    def __hash__(self):
        return hash(self.text)

    def __repr__(self):
        return "Instant(%r)" % self.text

    def __str__(self):
        return self.text


def _end(value):
    return dt.date.max if value is None else as_date(value)


def allen(a, b):
    """The Allen relation of interval ``a`` to interval ``b``.

    Intervals are (start, end) pairs with the end exclusive; an end of None
    means the interval is still open. Returns one of the thirteen relation
    names, e.g. "meets" when ``a`` ends on the day ``b`` begins.
    """
    s1, e1 = as_date(a[0]), _end(a[1])
    s2, e2 = as_date(b[0]), _end(b[1])
    if e1 < s2:
        return "before"
    if e2 < s1:
        return "after"
    if e1 == s2:
        return "meets"
    if e2 == s1:
        return "met-by"
    if s1 == s2 and e1 == e2:
        return "equals"
    if s1 == s2:
        return "starts" if e1 < e2 else "started-by"
    if e1 == e2:
        return "finishes" if s1 > s2 else "finished-by"
    if s2 < s1 and e1 < e2:
        return "during"
    if s1 < s2 and e2 < e1:
        return "contains"
    return "overlaps" if s1 < s2 else "overlapped-by"
