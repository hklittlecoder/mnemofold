"""Tests for mnemofold.clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from mnemofold.clock import Clock, ClockConfig, day_bucket, is_same_day, start_of_day

SAMPLE_START = datetime(2025, 1, 15, 9, 0, 0, tzinfo=UTC)


class TestClockConstruction:
    def test_default_start(self):
        c = Clock(seed=42)
        assert c.now().tzinfo is not None
        assert c.seed == 42

    def test_explicit_start(self):
        c = Clock(seed=1, start=SAMPLE_START)
        assert c.now() == SAMPLE_START

    def test_naive_start_rejected(self):
        naive = datetime(2025, 1, 1, 9, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            Clock(seed=1, start=naive)

    def test_negative_min_step_rejected(self):
        with pytest.raises(ValueError, match="min_step must be non-negative"):
            Clock(seed=1, start=SAMPLE_START, min_step=timedelta(seconds=-1))

    def test_max_step_less_than_min_rejected(self):
        with pytest.raises(ValueError, match="max_step must be >= min_step"):
            Clock(
                seed=1,
                start=SAMPLE_START,
                min_step=timedelta(minutes=10),
                max_step=timedelta(minutes=5),
            )


class TestClockDeterminism:
    def test_same_seed_same_tick_sequence(self):
        c1 = Clock(seed=12345, start=SAMPLE_START)
        c2 = Clock(seed=12345, start=SAMPLE_START)
        for _ in range(20):
            assert c1.tick() == c2.tick()

    def test_different_seeds_produce_different_sequences(self):
        c1 = Clock(seed=1, start=SAMPLE_START)
        c2 = Clock(seed=2, start=SAMPLE_START)
        # With very high probability they'll differ within 5 ticks
        ticks1 = [c1.tick() for _ in range(5)]
        ticks2 = [c2.tick() for _ in range(5)]
        assert ticks1 != ticks2

    def test_reset_restarts_sequence(self):
        c = Clock(seed=99, start=SAMPLE_START)
        first_pass = [c.tick() for _ in range(10)]
        c.reset()
        second_pass = [c.tick() for _ in range(10)]
        assert first_pass == second_pass

    def test_reset_returns_start_time(self):
        c = Clock(seed=7, start=SAMPLE_START)
        c.tick()
        assert c.reset() == SAMPLE_START


class TestClockMovement:
    def test_tick_always_advances(self):
        c = Clock(seed=5, start=SAMPLE_START)
        prev = c.now()
        for _ in range(10):
            new = c.tick()
            assert new > prev
            prev = new

    def test_tick_within_bounds(self):
        min_step = timedelta(minutes=5)
        max_step = timedelta(minutes=10)
        c = Clock(seed=3, start=SAMPLE_START, min_step=min_step, max_step=max_step)
        for _ in range(50):
            prev = c.now()
            new = c.tick()
            delta = new - prev
            assert min_step <= delta <= max_step + timedelta(microseconds=1)

    def test_advance(self):
        c = Clock(seed=1, start=SAMPLE_START)
        result = c.advance(timedelta(hours=2))
        assert result == SAMPLE_START + timedelta(hours=2)
        assert c.now() == SAMPLE_START + timedelta(hours=2)

    def test_advance_backward_rejected(self):
        c = Clock(seed=1, start=SAMPLE_START)
        with pytest.raises(ValueError, match="cannot advance backward"):
            c.advance(timedelta(minutes=-1))

    def test_set_forward(self):
        c = Clock(seed=1, start=SAMPLE_START)
        target = SAMPLE_START + timedelta(days=5)
        assert c.set(target) == target
        assert c.now() == target

    def test_set_backward_rejected(self):
        c = Clock(seed=1, start=SAMPLE_START)
        with pytest.raises(ValueError, match="cannot set clock backward"):
            c.set(SAMPLE_START - timedelta(minutes=1))

    def test_set_naive_rejected(self):
        c = Clock(seed=1, start=SAMPLE_START)
        with pytest.raises(ValueError, match="timezone-aware"):
            c.set(datetime(2025, 6, 1, 12, 0))  # type: ignore[arg-type]


class TestClockConfig:
    def test_config_construction(self):
        cfg = ClockConfig(seed=42, start=SAMPLE_START, min_step=timedelta(seconds=1))
        assert cfg.seed == 42
        assert cfg.start == SAMPLE_START


class TestDayBucket:
    def test_utc_day_bucket_simple(self):
        ts = datetime(2025, 3, 14, 12, 0, 0, tzinfo=UTC)
        assert day_bucket(ts, UTC) == date(2025, 3, 14)

    def test_utc_day_bucket_boundary_early_morning(self):
        ts = datetime(2025, 3, 14, 0, 0, 1, tzinfo=UTC)
        assert day_bucket(ts, UTC) == date(2025, 3, 14)

    def test_utc_day_bucket_boundary_late_night(self):
        ts = datetime(2025, 3, 14, 23, 59, 59, tzinfo=UTC)
        assert day_bucket(ts, UTC) == date(2025, 3, 14)

    def test_positive_offset_tz(self):
        # UTC+5 — 03:00 UTC is still the previous day local
        ts = datetime(2025, 3, 14, 3, 0, 0, tzinfo=UTC)
        tz_plus5 = timezone(timedelta(hours=5))
        assert day_bucket(ts, tz_plus5) == date(2025, 3, 14)

    def test_negative_offset_tz(self):
        # UTC-8 — 22:00 UTC is still the same day in UTC-8
        ts = datetime(2025, 3, 14, 22, 0, 0, tzinfo=UTC)
        tz_minus8 = timezone(timedelta(hours=-8))
        assert day_bucket(ts, tz_minus8) == date(2025, 3, 14)

    def test_naive_timestamp_rejected(self):
        naive = datetime(2025, 3, 14, 12, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            day_bucket(naive, UTC)


class TestStartOfDay:
    def test_start_of_day_utc(self):
        d = date(2025, 6, 15)
        sod = start_of_day(d, UTC)
        assert sod == datetime(2025, 6, 15, 0, 0, 0, tzinfo=UTC)

    def test_start_of_day_fixed_offset(self):
        d = date(2025, 6, 15)
        tz = timezone(timedelta(hours=5, minutes=30))
        sod = start_of_day(d, tz)
        # The local midnight exists for fixed-offset timezones
        assert sod.hour == 0
        assert sod.minute == 0
        # Convert back to UTC to verify the offset is correct
        assert sod.astimezone(UTC) == datetime(2025, 6, 14, 18, 30, 0, tzinfo=UTC)


class TestIsSameDay:
    def test_same_day_same_time(self):
        a = datetime(2025, 3, 14, 10, 0, 0, tzinfo=UTC)
        b = datetime(2025, 3, 14, 15, 0, 0, tzinfo=UTC)
        assert is_same_day(a, b, UTC)

    def test_different_days(self):
        a = datetime(2025, 3, 14, 23, 0, 0, tzinfo=UTC)
        b = datetime(2025, 3, 15, 1, 0, 0, tzinfo=UTC)
        assert not is_same_day(a, b, UTC)

    def test_same_day_different_tz_perspective(self):
        # Both times are on March 14 UTC, but in UTC+10 the second is next day
        a = datetime(2025, 3, 14, 10, 0, 0, tzinfo=UTC)
        b = datetime(2025, 3, 14, 20, 0, 0, tzinfo=UTC)
        tz_plus10 = timezone(timedelta(hours=10))
        assert is_same_day(a, b, UTC)
        assert not is_same_day(a, b, tz_plus10)
