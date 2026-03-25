"""Day bucketing across the 2026 IANA DST transitions.

US: spring forward 2026-03-08 02:00, fall back 2026-11-01 02:00
(America/New_York). EU: spring forward 2026-03-29, fall back
2026-10-25 (Europe/Berlin). Fixed-offset tests elsewhere cannot catch
bucketing bugs that only appear when the UTC offset changes mid-day.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mnemofold.clock import day_bucket, is_same_day, start_of_day

NY = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")


class TestSpringForwardNY:
    def test_utc_instant_before_local_midnight_stays_previous_day(self):
        # 2026-03-08T04:59Z == 2026-03-07 23:59 EST
        ts = datetime(2026, 3, 8, 4, 59, tzinfo=UTC)
        assert day_bucket(ts, NY) == date(2026, 3, 7)

    def test_utc_instant_at_local_midnight_flips_day(self):
        # 2026-03-08T05:00Z == 2026-03-08 00:00 EST
        ts = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
        assert day_bucket(ts, NY) == date(2026, 3, 8)

    def test_both_sides_of_the_2am_jump_share_one_day(self):
        before = datetime(2026, 3, 8, 6, 59, tzinfo=UTC)  # 01:59 EST
        after = datetime(2026, 3, 8, 7, 1, tzinfo=UTC)  # 03:01 EDT
        assert day_bucket(before, NY) == day_bucket(after, NY) == date(2026, 3, 8)
        assert after - before == timedelta(minutes=2)

    def test_start_of_day_before_and_after_transition(self):
        assert start_of_day(date(2026, 3, 8), NY).utcoffset() == timedelta(hours=-5)
        assert start_of_day(date(2026, 3, 9), NY).utcoffset() == timedelta(hours=-4)


class TestFallBackNY:
    def test_ambiguous_local_hour_lands_on_same_day(self):
        first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT
        second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)  # 01:30 EST
        assert day_bucket(first, NY) == day_bucket(second, NY) == date(2026, 11, 1)

    def test_offsets_differ_across_the_transition(self):
        before = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
        after = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
        assert before.astimezone(NY).utcoffset() == timedelta(hours=-4)
        assert after.astimezone(NY).utcoffset() == timedelta(hours=-5)


class TestBerlin:
    def test_day_flips_at_local_midnight_cet(self):
        before = datetime(2026, 3, 28, 22, 59, tzinfo=UTC)  # 23:59 CET Mar 28
        after = datetime(2026, 3, 28, 23, 0, tzinfo=UTC)  # 00:00 CET Mar 29
        assert day_bucket(before, BERLIN) == date(2026, 3, 28)
        assert day_bucket(after, BERLIN) == date(2026, 3, 29)

    def test_transition_day_keeps_one_bucket(self):
        early = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)  # 01:30 CET
        late = datetime(2026, 3, 29, 22, 30, tzinfo=UTC)  # 00:30 CEST on Mar 30
        assert day_bucket(early, BERLIN) == date(2026, 3, 29)
        assert day_bucket(late, BERLIN) == date(2026, 3, 30)


class TestSameDayAcrossZones:
    def test_same_instant_pair_agrees_in_one_zone_disagrees_in_another(self):
        a = datetime(2026, 3, 8, 4, 30, tzinfo=UTC)  # Mar 7 23:30 in NY
        b = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)  # Mar 7 07:00 in NY
        assert is_same_day(a, b, NY)
        assert not is_same_day(a, b, UTC)

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValueError):
            day_bucket(datetime(2026, 3, 8, 4, 30), NY)
