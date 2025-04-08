"""Temporal model: interval-valid facts and as-of queries.

Implements interval-valid facts (valid_from / valid_to), an as-of query
engine that answers "what was known on date D", staleness detection,
working-day calendars, and deadline arithmetic across time zones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def _parse_instant(value: str) -> datetime:
    """Parse an ISO timestamp into an aware datetime (naive means UTC)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@dataclass(slots=True)
class IntervalFact(Generic[T]):
    """A fact that is valid during a time interval.

    valid_from is inclusive, valid_to is exclusive (None = still valid).
    """

    fact_key: str
    value: T
    valid_from: str  # ISO datetime
    valid_to: str | None = None  # None means currently valid
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid_at(self, when: str) -> bool:
        """Check if this fact was valid at the given datetime.

        Bounds are compared as instants, not as strings: the same moment
        expressed with different UTC offsets gives the same answer.
        """
        moment = _parse_instant(when)
        if moment < _parse_instant(self.valid_from):
            return False
        if self.valid_to is None:
            return True
        return moment < _parse_instant(self.valid_to)

    def is_current(self) -> bool:
        """Check if this fact is still valid (no end date)."""
        return self.valid_to is None


@dataclass
class TemporalStore(Generic[T]):
    """Stores interval-valid facts and supports as-of queries.

    For each fact key, at most one version is active at any given time.
    Superseded versions remain queryable via as-of.
    """

    _facts: list[IntervalFact[T]] = field(default_factory=list)

    def add(self, fact: IntervalFact[T]) -> None:
        """Add a fact. Does not enforce key ordering constraints."""
        self._facts.append(fact)

    def current(self, fact_key: str) -> IntervalFact[T] | None:
        """Return the currently-active version of a fact key."""
        for f in reversed(self._facts):
            if f.fact_key == fact_key and f.is_current():
                return f
        return None

    def as_of(self, fact_key: str, when: str) -> IntervalFact[T] | None:
        """Return the version of fact_key that was valid at time 'when'.

        If multiple facts with the same key overlap 'when' (which shouldn't
        happen if the store is well-formed), returns the most recently
        started one.
        """
        best: IntervalFact[T] | None = None
        for f in self._facts:
            if f.fact_key != fact_key:
                continue
            if not f.is_valid_at(when):
                continue
            if best is None or _parse_instant(f.valid_from) > _parse_instant(best.valid_from):
                best = f
        return best

    def history(self, fact_key: str) -> list[IntervalFact[T]]:
        """Return all versions of a fact key, oldest first."""
        return sorted(
            [f for f in self._facts if f.fact_key == fact_key],
            key=lambda f: _parse_instant(f.valid_from),
        )

    def all_current(self) -> list[IntervalFact[T]]:
        """Return all currently-valid facts."""
        return [f for f in self._facts if f.is_current()]

    def keys(self) -> list[str]:
        """Return all distinct fact keys."""
        return sorted({f.fact_key for f in self._facts})

    def staleness(self, fact_key: str, now: str, max_age_days: float = 30.0) -> float:
        """Return staleness score (0 = fresh, 1+ = stale).

        Staleness = age_days / max_age_days. Values > 1 mean the fact
        is older than max_age_days.
        """
        cur = self.current(fact_key)
        if cur is None:
            return float("inf")
        try:
            t_now = _parse_instant(now)
            t_from = _parse_instant(cur.valid_from)
        except (ValueError, TypeError):
            return float("inf")
        age_days = (t_now - t_from).total_seconds() / 86400.0
        return age_days / max_age_days if max_age_days > 0 else float("inf")

    def superseded_count(self) -> int:
        """Count of facts that have been superseded (have valid_to set)."""
        return sum(1 for f in self._facts if not f.is_current())


# Working day calendars


@dataclass
class WorkdayCalendar:
    """A working-day calendar for a specific region.

    Supports configurable weekends and holiday lists. Provides deadline
    arithmetic: add N working days to a date.
    """

    name: str
    weekend_days: set[int] = field(default_factory=lambda: {5, 6})  # Sat, Sun
    holidays: set[str] = field(default_factory=set)  # set of YYYY-MM-DD

    def is_workday(self, d: date) -> bool:
        """Check if a date is a working day."""
        if d.weekday() in self.weekend_days:
            return False
        return d.isoformat() not in self.holidays

    def add_workdays(self, start: date, days: int) -> date:
        """Add 'days' working days to 'start'.

        If days is negative, subtracts working days.
        """
        if days == 0:
            return start
        step = 1 if days > 0 else -1
        remaining = abs(days)
        current = start
        while remaining > 0:
            current += timedelta(days=step)
            if self.is_workday(current):
                remaining -= 1
        return current

    def workdays_between(self, start: date, end: date) -> int:
        """Count working days between start (inclusive) and end (exclusive)."""
        if end < start:
            return -self.workdays_between(end, start)
        count = 0
        d = start
        while d < end:
            if self.is_workday(d):
                count += 1
            d += timedelta(days=1)
        return count

    def next_workday(self, d: date) -> date:
        """Return the next working day on or after d."""
        current = d
        while not self.is_workday(current):
            current += timedelta(days=1)
        return current


def deadline_overdue(due: str, now: str, grace_hours: float = 0.0) -> bool:
    """Check if a deadline is overdue.

    'due' and 'now' are ISO datetime strings.
    grace_hours extends the deadline by that many hours.
    """
    try:
        t_due = _parse_instant(due)
        t_now = _parse_instant(now)
    except (ValueError, TypeError):
        return False
    grace = timedelta(hours=grace_hours)
    return t_now > (t_due + grace)


def time_until_deadline(due: str, now: str) -> timedelta | None:
    """Return the time remaining until a deadline.

    Returns None if parsing fails. Returns negative timedelta if overdue.
    """
    try:
        t_due = _parse_instant(due)
        t_now = _parse_instant(now)
    except (ValueError, TypeError):
        return None
    return t_due - t_now
