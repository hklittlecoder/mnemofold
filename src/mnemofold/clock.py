"""Deterministic clock and time utilities for mnemofold.

The synthetic clock is backed by a seeded RNG so that simulations and
tests produce the exact same sequence of timestamps every run.  It also
provides timezone-safe day bucketing helpers that handle DST transitions
correctly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum


class DayBoundary(StrEnum):
    """How to bucket events into days."""

    UTC = "utc"
    LOCAL_MIDNIGHT = "local_midnight"
    WORKDAY_START = "workday_start"


@dataclass(frozen=True)
class ClockConfig:
    """Configuration for a Clock instance."""

    seed: int
    start: datetime
    min_step: timedelta = timedelta(seconds=30)
    max_step: timedelta = timedelta(minutes=30)


class Clock:
    """A deterministic clock that produces timestamped values.

    Given the same seed, the same sequence of calls yields the same
    sequence of datetimes.  This is essential for byte-for-byte replay.

    The clock starts at ``start`` and moves forward only.  Each call to
    ``tick`` advances by a random delta drawn from
    ``[min_step, max_step]`` (uniform).  ``advance`` lets the caller
    jump forward by a specific amount.
    """

    def __init__(
        self,
        seed: int,
        start: datetime | None = None,
        min_step: timedelta = timedelta(seconds=30),
        max_step: timedelta = timedelta(minutes=30),
    ) -> None:
        if start is None:
            start = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        if min_step < timedelta(0):
            raise ValueError("min_step must be non-negative")
        if max_step < min_step:
            raise ValueError("max_step must be >= min_step")
        self._start = start
        self._now = start
        self._rng = random.Random(seed)
        self._min_step = min_step
        self._max_step = max_step
        self._seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def start(self) -> datetime:
        return self._start

    def now(self) -> datetime:
        """Return the current clock time (does not advance)."""
        return self._now

    def tick(self) -> datetime:
        """Advance the clock by a random step and return the new time."""
        delta_seconds = self._rng.uniform(
            self._min_step.total_seconds(),
            self._max_step.total_seconds(),
        )
        self._now += timedelta(seconds=delta_seconds)
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """Advance the clock by a specific delta and return the new time."""
        if delta < timedelta(0):
            raise ValueError("cannot advance backward")
        self._now += delta
        return self._now

    def set(self, target: datetime) -> datetime:
        """Jump to a specific time (must not be earlier than current)."""
        if target.tzinfo is None:
            raise ValueError("target must be timezone-aware")
        if target < self._now:
            raise ValueError("cannot set clock backward")
        self._now = target
        return self._now

    def reset(self) -> datetime:
        """Reset the clock to its initial state.

        The RNG is reseeded so the same tick sequence is produced again.
        Returns the new (initial) time.
        """
        self._rng = random.Random(self._seed)
        self._now = self._start
        return self._now


def day_bucket(ts: datetime, tz: timezone = UTC) -> date:
    """Return the calendar day for ``ts`` when viewed in ``tz``.

    Handles DST transitions correctly because the conversion goes
    through the timezone-aware timestamp rather than naively truncating.
    """
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    local = ts.astimezone(tz)
    return local.date()


def start_of_day(d: date, tz: timezone = UTC) -> datetime:
    """Return the first instant of date ``d`` in timezone ``tz``.

    On DST-transition days where midnight may not exist (spring forward),
    this returns the first valid instant after transition — typically
    01:00 — which is the correct "start of day" for bucketing purposes.
    """
    # Construct the earliest possible local datetime and let astimezone
    # handle ambiguity.  For DST transitions where midnight doesn't
    # exist, fromisoformat of the date string plus tzinfo will raise in
    # some implementations — instead, use combine and fold semantics.
    naive = datetime.combine(d, datetime.min.time())
    try:
        local = naive.replace(tzinfo=tz)
        # Force a round-trip through UTC to validate the local time exists
        local.astimezone(UTC)
        return local
    except (ValueError, OverflowError) as err:
        # If midnight doesn't exist, try each hour forward until we find
        # one that does.  This handles spring-forward transitions where
        # 00:00 -> 01:00 is skipped.
        for hour in range(1, 24):
            try:
                local = naive.replace(hour=hour, tzinfo=tz)
                local.astimezone(UTC)
                return local
            except (ValueError, OverflowError):
                continue
        raise ValueError(f"Date {d} has no valid local time in {tz}") from err


def is_same_day(a: datetime, b: datetime, tz: timezone = UTC) -> bool:
    """Return True if two timestamps fall on the same calendar day in tz."""
    return day_bucket(a, tz) == day_bucket(b, tz)
