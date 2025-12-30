"""Temporal model: interval-valid facts and as-of queries.

Implements interval-valid facts (valid_from / valid_to), an as-of query
engine that answers "what was known on date D", staleness detection,
working-day calendars, and deadline arithmetic across time zones.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Generic, TypeVar
from zoneinfo import ZoneInfo

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

    def snapshot_at(self, when: str) -> dict[str, IntervalFact[T]]:
        """Bulk as-of query: every fact key with its version valid at ``when``.

        Keys with no version covering the instant are absent, so the
        snapshot answers "what was known at ``when``" in one call. Keys
        are emitted in sorted order and each value is exactly what
        :meth:`as_of` returns for that key, including its tie-break.
        """
        return {key: fact for key in self.keys() if (fact := self.as_of(key, when)) is not None}

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

    def supersede(
        self,
        fact_key: str,
        new_value: T,
        at: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> IntervalFact[T]:
        """Close the current version (if any) at ``at`` and open a new one.

        ``at`` becomes the new version's inclusive ``valid_from`` and the
        previous version's exclusive ``valid_to``, so as-of queries from
        before ``at`` keep returning the old value: history is never
        lost. Callers pass an ``at`` at or after the current version's
        start; an earlier instant produces an overlap that
        :class:`IntervalValidator` reports rather than one this method
        silently rewrites. Returns the newly added fact.
        """
        current = self.current(fact_key)
        if current is not None:
            current.valid_to = at
        fact: IntervalFact[T] = IntervalFact(
            fact_key=fact_key,
            value=new_value,
            valid_from=at,
            metadata=dict(metadata or {}),
        )
        self._facts.append(fact)
        return fact


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


# --- Regional calendar registry ----------------------------------------------

# Representative public-holiday sets for 2025, one per supported region.
# These cover the fixed-date and well-known movable holidays needed by the
# synthetic factory, examples, and deadline arithmetic tests; they are not
# an authoritative statutory calendar service.
HOLIDAYS_2025: dict[str, frozenset[str]] = {
    "hk": frozenset(
        {
            "2025-01-01",  # New Year's Day
            "2025-01-29",  # Lunar New Year (day 1)
            "2025-01-30",  # Lunar New Year (day 2)
            "2025-01-31",  # Lunar New Year (day 3)
            "2025-04-04",  # Ching Ming
            "2025-05-01",  # Labour Day
            "2025-10-01",  # National Day
            "2025-12-25",  # Christmas
            "2025-12-26",  # Boxing Day
        }
    ),
    "us": frozenset(
        {
            "2025-01-01",  # New Year's Day
            "2025-01-20",  # Martin Luther King Jr. Day
            "2025-02-17",  # Washington's Birthday
            "2025-05-26",  # Memorial Day
            "2025-06-19",  # Juneteenth
            "2025-07-04",  # Independence Day
            "2025-09-01",  # Labor Day
            "2025-11-27",  # Thanksgiving
            "2025-12-25",  # Christmas
        }
    ),
    "de": frozenset(
        {
            "2025-01-01",  # Neujahr
            "2025-04-18",  # Good Friday
            "2025-04-21",  # Easter Monday
            "2025-05-01",  # Labour Day
            "2025-05-29",  # Ascension
            "2025-06-09",  # Whit Monday
            "2025-10-03",  # German Unity Day
            "2025-12-25",  # Christmas
            "2025-12-26",  # Second Christmas Day
        }
    ),
}

# Representative public-holiday sets for 2026, mirroring the 2025 tables.
# Movable dates follow the 2026 ecclesiastical calendar (Easter Sunday is
# April 5) and the US federal weekday rules; like the 2025 tables they are
# representative fixtures for offline scenarios, not a statutory source.
HOLIDAYS_2026: dict[str, frozenset[str]] = {
    "de": frozenset(
        {
            "2026-01-01",  # Neujahr
            "2026-04-03",  # Good Friday
            "2026-04-06",  # Easter Monday
            "2026-05-01",  # Labour Day
            "2026-05-14",  # Ascension
            "2026-05-25",  # Whit Monday
            "2026-10-03",  # German Unity Day
            "2026-12-25",  # Christmas
            "2026-12-26",  # Second Christmas Day
        }
    ),
    "hk": frozenset(
        {
            "2026-01-01",  # New Year's Day
            "2026-02-17",  # Lunar New Year (day 1)
            "2026-02-18",  # Lunar New Year (day 2)
            "2026-02-19",  # Lunar New Year (day 3)
            "2026-04-06",  # Ching Ming (observed)
            "2026-05-01",  # Labour Day
            "2026-10-01",  # National Day
            "2026-12-25",  # Christmas
            "2026-12-26",  # Boxing Day
        }
    ),
    "us": frozenset(
        {
            "2026-01-01",  # New Year's Day
            "2026-01-19",  # Martin Luther King Jr. Day
            "2026-02-16",  # Washington's Birthday
            "2026-05-25",  # Memorial Day
            "2026-06-19",  # Juneteenth
            "2026-07-03",  # Independence Day (observed)
            "2026-09-07",  # Labor Day
            "2026-11-26",  # Thanksgiving
            "2026-12-25",  # Christmas
        }
    ),
}

# Holiday tables keyed by year; the registry merges the requested years.
HOLIDAYS_BY_YEAR: dict[int, dict[str, frozenset[str]]] = {
    2025: HOLIDAYS_2025,
    2026: HOLIDAYS_2026,
}


# IANA zone names per region, used by wall-clock deadline arithmetic.
REGION_TIMEZONES: dict[str, str] = {
    "hk": "Asia/Hong_Kong",
    "us": "America/New_York",
    "de": "Europe/Berlin",
}


@dataclass
class CalendarRegistry:
    """Named regional working-day calendars.

    ``with_defaults()`` builds the representative 2025 registries; extra
    regions can be registered at runtime. Region lookup is deterministic
    and unknown regions raise rather than silently falling back.
    """

    _calendars: dict[str, WorkdayCalendar] = field(default_factory=dict)

    def register(self, calendar: WorkdayCalendar) -> None:
        self._calendars[calendar.name] = calendar

    def get(self, region: str) -> WorkdayCalendar:
        try:
            return self._calendars[region]
        except KeyError:
            raise KeyError(f"unknown calendar region: {region}") from None

    def regions(self) -> list[str]:
        return sorted(self._calendars)

    @classmethod
    def with_defaults(cls, years: tuple[int, ...] = (2025,)) -> CalendarRegistry:
        """Build regional calendars from the representative holiday tables.

        ``years`` selects which tables to merge into each region's
        holiday set; the default keeps the historical 2025-only
        behavior. Unknown years raise instead of silently producing a
        holiday-free calendar.
        """
        for year in years:
            if year not in HOLIDAYS_BY_YEAR:
                raise KeyError(f"no representative holiday table for year: {year}")
        registry = cls()
        for region in sorted(HOLIDAYS_2025):
            merged: set[str] = set()
            for year in years:
                merged |= set(HOLIDAYS_BY_YEAR[year][region])
            registry.register(WorkdayCalendar(name=region, holidays=merged))
        return registry


# --- Wall-clock deadlines -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class WallDeadline:
    """A deadline anchored to local wall time in one region.

    "Submit by 17:00 New York time on 2025-03-14" denotes an instant that
    shifts with the region's UTC offset (DST included), so overdue checks
    must resolve the wall time through the region's IANA zone rather than
    assume a fixed offset.
    """

    day: str  # YYYY-MM-DD, interpreted in region_tz
    hour: int
    minute: int
    region_tz: str

    def instant(self) -> datetime:
        """The deadline as one concrete tz-aware instant."""
        tz = ZoneInfo(self.region_tz)
        wall = time(hour=self.hour, minute=self.minute)
        return datetime.combine(date.fromisoformat(self.day), wall, tzinfo=tz)

    def is_overdue(self, now: datetime, grace_hours: float = 0.0) -> bool:
        """Whether ``now`` (any timezone) is past the deadline plus grace."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return now > self.instant() + timedelta(hours=grace_hours)

    def rolled_to_workday(self, calendar: WorkdayCalendar) -> WallDeadline:
        """Same wall time, moved forward to the next working day if needed."""
        rolled = calendar.next_workday(date.fromisoformat(self.day))
        return replace(self, day=rolled.isoformat())


def wall_deadline_in(region: str, day: str, hour: int = 17, minute: int = 0) -> WallDeadline:
    """Build a wall-clock deadline from a registry region name."""
    try:
        tz_name = REGION_TIMEZONES[region]
    except KeyError:
        raise ValueError(f"unknown calendar region: {region}") from None
    return WallDeadline(day=day, hour=hour, minute=minute, region_tz=tz_name)


# --- Staleness policy ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StalenessPolicy:
    """Turns raw staleness ratios into deterministic, documented classes.

    ``ratio = age_days / max_age_days`` (as computed by
    :meth:`TemporalStore.staleness`). Classification thresholds:

    * ``ratio < warn_at``            -> ``"fresh"``
    * ``warn_at <= ratio < 1.0``     -> ``"aging"``
    * ``1.0 <= ratio < expire_at``   -> ``"stale"``
    * ``ratio >= expire_at``         -> ``"expired"``
    * fact missing or unparseable    -> ``"unknown"``
    """

    max_age_days: float = 30.0
    warn_at: float = 0.7
    expire_at: float = 2.0

    def classify_ratio(self, ratio: float) -> str:
        if ratio != ratio or ratio == float("inf"):  # NaN or unbounded
            return "expired"
        if ratio < self.warn_at:
            return "fresh"
        if ratio < 1.0:
            return "aging"
        if ratio < self.expire_at:
            return "stale"
        return "expired"

    def classify(self, store: TemporalStore[Any], fact_key: str, now: str) -> str:
        if store.current(fact_key) is None:
            return "unknown"
        ratio = store.staleness(fact_key, now, max_age_days=self.max_age_days)
        return self.classify_ratio(ratio)


# --- Interval validation -------------------------------------------------------


@dataclass(slots=True)
class IntervalViolation:
    """One overlap found in a fact key's validity history."""

    fact_key: str
    earlier_value: Any
    later_value: Any
    overlap_start: str  # instant the two versions both claim (ISO)
    overlap_end: str | None  # None when the overlap is open-ended


@dataclass
class IntervalValidator:
    """Checks the "one active version per fact key" structural invariant.

    A well-formed history tiles the timeline: each version ends exactly
    when the next begins. Overlaps mean two versions claim the same
    instant, which makes as-of answers ambiguous; gaps are legal (the
    fact was simply unknown for a while) and are not reported.
    """

    def validate(self, store: TemporalStore[Any]) -> list[IntervalViolation]:
        violations: list[IntervalViolation] = []
        fact_keys = store.keys()
        for fact_key in fact_keys:
            versions = store.history(fact_key)
            for earlier, later in zip(versions, versions[1:], strict=False):
                later_start = _parse_instant(later.valid_from)
                if earlier.valid_to is None:
                    violations.append(
                        IntervalViolation(
                            fact_key=fact_key,
                            earlier_value=earlier.value,
                            later_value=later.value,
                            overlap_start=later.valid_from,
                            overlap_end=None,
                        )
                    )
                    continue
                earlier_end = _parse_instant(earlier.valid_to)
                if earlier_end > later_start:
                    overlap_end = (
                        earlier.valid_to
                        if later.valid_to is None
                        else min(earlier_end, _parse_instant(later.valid_to)).isoformat()
                    )
                    violations.append(
                        IntervalViolation(
                            fact_key=fact_key,
                            earlier_value=earlier.value,
                            later_value=later.value,
                            overlap_start=later.valid_from,
                            overlap_end=overlap_end,
                        )
                    )
        return violations
