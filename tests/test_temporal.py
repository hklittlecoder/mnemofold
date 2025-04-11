"""Tests for the temporal model module."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mnemofold.temporal import (
    CalendarRegistry,
    IntervalFact,
    TemporalStore,
    WallDeadline,
    WorkdayCalendar,
    deadline_overdue,
    time_until_deadline,
    wall_deadline_in,
)


class TestIntervalFact:
    def test_is_valid_at_inclusive_start(self):
        f = IntervalFact(
            "status", "active", "2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"
        )
        assert f.is_valid_at("2024-01-01T00:00:00+00:00")

    def test_is_valid_at_exclusive_end(self):
        f = IntervalFact(
            "status", "active", "2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"
        )
        assert not f.is_valid_at("2024-02-01T00:00:00+00:00")

    def test_is_valid_mid_range(self):
        f = IntervalFact("status", "x", "2024-01-01T00:00:00+00:00", "2024-01-31T00:00:00+00:00")
        assert f.is_valid_at("2024-01-15T12:00:00+00:00")

    def test_is_current_no_end(self):
        f = IntervalFact("status", "x", "2024-01-01T00:00:00+00:00")
        assert f.is_current()

    def test_not_current_with_end(self):
        f = IntervalFact("status", "x", "2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00")
        assert not f.is_current()


class TestTemporalStore:
    def test_current_fact(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("owner", "alice", "2024-01-01T00:00:00+00:00"))
        cur = store.current("owner")
        assert cur is not None
        assert cur.value == "alice"

    def test_as_of_returns_correct_version(self):
        store = TemporalStore[str]()
        store.add(
            IntervalFact("owner", "alice", "2024-01-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00")
        )
        store.add(IntervalFact("owner", "bob", "2024-03-01T00:00:00+00:00"))

        jan = store.as_of("owner", "2024-01-15T00:00:00+00:00")
        assert jan is not None
        assert jan.value == "alice"

        mar = store.as_of("owner", "2024-03-15T00:00:00+00:00")
        assert mar is not None
        assert mar.value == "bob"

    def test_as_of_before_any_fact(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("owner", "alice", "2024-01-01T00:00:00+00:00"))
        assert store.as_of("owner", "2023-01-01T00:00:00+00:00") is None

    def test_history_ordered_oldest_first(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("s", "v1", "2024-03-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00"))
        store.add(IntervalFact("s", "v2", "2024-04-01T00:00:00+00:00", "2024-05-01T00:00:00+00:00"))
        store.add(IntervalFact("s", "v3", "2024-05-01T00:00:00+00:00"))
        hist = store.history("s")
        assert len(hist) == 3
        assert hist[0].value == "v1"
        assert hist[1].value == "v2"
        assert hist[2].value == "v3"

    def test_superseded_count(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("s", "v1", "2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"))
        store.add(IntervalFact("s", "v2", "2024-02-01T00:00:00+00:00"))
        assert store.superseded_count() == 1

    def test_staleness_fresh(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("s", "v", "2024-01-01T00:00:00+00:00"))
        s = store.staleness("s", "2024-01-05T00:00:00+00:00", max_age_days=30)
        assert s < 1.0

    def test_staleness_stale(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("s", "v", "2024-01-01T00:00:00+00:00"))
        s = store.staleness("s", "2024-03-01T00:00:00+00:00", max_age_days=30)
        assert s >= 1.0

    def test_all_current(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("a", "1", "2024-01-01T00:00:00+00:00"))
        store.add(IntervalFact("b", "2", "2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"))
        store.add(IntervalFact("c", "3", "2024-01-01T00:00:00+00:00"))
        assert len(store.all_current()) == 2

    def test_keys_distinct(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("a", "v1", "2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"))
        store.add(IntervalFact("a", "v2", "2024-02-01T00:00:00+00:00"))
        store.add(IntervalFact("b", "v3", "2024-01-01T00:00:00+00:00"))
        assert store.keys() == ["a", "b"]


class TestWorkdayCalendar:
    def test_default_weekends(self):
        cal = WorkdayCalendar("test")
        # 2024-01-01 is a Monday
        assert cal.is_workday(date(2024, 1, 1))
        assert not cal.is_workday(date(2024, 1, 6))  # Saturday
        assert not cal.is_workday(date(2024, 1, 7))  # Sunday

    def test_add_workdays_skip_weekends(self):
        cal = WorkdayCalendar("test")
        # 2024-01-05 is Friday
        result = cal.add_workdays(date(2024, 1, 5), 3)
        assert result == date(2024, 1, 10)  # Mon + Tue + Wed

    def test_add_workdays_zero(self):
        cal = WorkdayCalendar("test")
        assert cal.add_workdays(date(2024, 1, 15), 0) == date(2024, 1, 15)

    def test_add_workdays_negative(self):
        cal = WorkdayCalendar("test")
        # 2024-01-08 is Monday, go back 3 workdays -> Wed Jan 3
        result = cal.add_workdays(date(2024, 1, 8), -3)
        assert result == date(2024, 1, 3)

    def test_holidays(self):
        cal = WorkdayCalendar("test", holidays={"2024-01-01"})
        assert not cal.is_workday(date(2024, 1, 1))  # Monday but holiday

    def test_workdays_between(self):
        cal = WorkdayCalendar("test")
        # Jan 1 (Mon) to Jan 8 (Mon) = 5 workdays
        count = cal.workdays_between(date(2024, 1, 1), date(2024, 1, 8))
        assert count == 5

    def test_next_workday_on_weekend(self):
        cal = WorkdayCalendar("test")
        # Jan 6, 2024 is Saturday
        assert cal.next_workday(date(2024, 1, 6)) == date(2024, 1, 8)

    def test_next_workday_on_workday(self):
        cal = WorkdayCalendar("test")
        assert cal.next_workday(date(2024, 1, 3)) == date(2024, 1, 3)  # Wednesday


class TestDeadline:
    def test_not_overdue_before_deadline(self):
        assert not deadline_overdue("2024-01-15T00:00:00+00:00", "2024-01-10T00:00:00+00:00")

    def test_overdue_after_deadline(self):
        assert deadline_overdue("2024-01-15T00:00:00+00:00", "2024-01-20T00:00:00+00:00")

    def test_grace_period(self):
        # 1 hour late, but 2 hour grace = not overdue
        assert not deadline_overdue(
            "2024-01-15T00:00:00+00:00",
            "2024-01-15T01:00:00+00:00",
            grace_hours=2.0,
        )

    def test_time_until_deadline_positive(self):
        delta = time_until_deadline("2024-01-15T00:00:00+00:00", "2024-01-10T00:00:00+00:00")
        assert delta is not None
        assert delta > timedelta(0)

    def test_time_until_deadline_negative(self):
        delta = time_until_deadline("2024-01-10T00:00:00+00:00", "2024-01-15T00:00:00+00:00")
        assert delta is not None
        assert delta < timedelta(0)


class TestInstantComparisons:
    def test_same_instant_different_offsets_agrees(self):
        f = IntervalFact(
            "status", "active", "2024-01-01T08:00:00+08:00", "2024-02-01T00:00:00+00:00"
        )
        # 2024-01-01T00:00:00Z is the same instant as the +08:00 start
        assert f.is_valid_at("2024-01-01T00:00:00+00:00")

    def test_just_before_start_in_other_offset(self):
        f = IntervalFact("status", "active", "2024-01-01T08:00:00+08:00")
        # start is 2024-01-01T00:00:00Z; one second earlier in UTC is outside
        assert not f.is_valid_at("2023-12-31T23:59:59+00:00")

    def test_lexicographic_order_would_be_wrong(self):
        # "2024-01-01T09:00:00+08:00" sorts after "2024-01-01T01:45:00+00:00"
        # as text, but as instants it is 01:00Z — inside the interval.
        f = IntervalFact("s", "v", "2024-01-01T00:00:00+00:00", "2024-01-01T01:30:00+00:00")
        assert f.is_valid_at("2024-01-01T09:00:00+08:00")
        assert not f.is_valid_at("2024-01-01T10:00:00+08:00")

    def test_as_of_picks_later_start_across_offsets(self):
        store = TemporalStore[str]()
        # starts 04:00Z, though its ISO string sorts after the 06:00Z one
        store.add(
            IntervalFact("owner", "early", "2024-01-01T12:00:00+08:00", "2024-06-01T00:00:00+00:00")
        )
        store.add(
            IntervalFact("owner", "late", "2024-01-01T06:00:00+00:00", "2024-06-01T00:00:00+00:00")
        )
        got = store.as_of("owner", "2024-03-01T00:00:00+00:00")
        assert got is not None
        assert got.value == "late"

    def test_history_sorts_by_instant_not_text(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("s", "b", "2024-01-02T00:00:00+00:00"))
        store.add(IntervalFact("s", "a", "2024-01-01T20:00:00-08:00"))  # == 01-02T04:00Z
        assert [f.value for f in store.history("s")] == ["b", "a"]

    def test_invalid_timestamp_raises(self):
        f = IntervalFact("s", "v", "2024-01-01T00:00:00+00:00")
        with pytest.raises(ValueError):
            f.is_valid_at("not-a-date")


class TestCalendarRegistry:
    def test_defaults_cover_expected_regions(self):
        registry = CalendarRegistry.with_defaults()
        assert registry.regions() == ["de", "hk", "us"]

    def test_hk_lunar_new_year_is_not_a_workday(self):
        calendar = CalendarRegistry.with_defaults().get("hk")
        assert not calendar.is_workday(date(2025, 1, 29))
        assert not calendar.is_workday(date(2025, 1, 31))
        # the following Monday is a normal workday
        assert calendar.is_workday(date(2025, 2, 3))

    def test_us_federal_holidays(self):
        calendar = CalendarRegistry.with_defaults().get("us")
        assert not calendar.is_workday(date(2025, 1, 20))  # MLK Day
        assert not calendar.is_workday(date(2025, 11, 27))  # Thanksgiving
        assert calendar.is_workday(date(2025, 11, 28))

    def test_de_movable_holidays(self):
        calendar = CalendarRegistry.with_defaults().get("de")
        assert not calendar.is_workday(date(2025, 4, 18))  # Good Friday
        assert not calendar.is_workday(date(2025, 4, 21))  # Easter Monday
        assert not calendar.is_workday(date(2025, 10, 3))  # Unity Day

    def test_deadline_arithmetic_skips_region_holidays(self):
        calendar = CalendarRegistry.with_defaults().get("hk")
        # Fri 2025-01-24 + 3 workdays: Mon 27, Tue 28, then the Lunar New
        # Year block (29-31) and weekend are skipped -> Mon 2025-02-03.
        assert calendar.add_workdays(date(2025, 1, 24), 3) == date(2025, 2, 3)

    def test_unknown_region_raises(self):
        with pytest.raises(KeyError, match="unknown calendar region"):
            CalendarRegistry.with_defaults().get("fr")

    def test_custom_region_registration(self):
        registry = CalendarRegistry()
        registry.register(WorkdayCalendar(name="lab", weekend_days={4, 5}))
        assert registry.regions() == ["lab"]
        # Friday is a weekend day in this lab
        assert not registry.get("lab").is_workday(date(2025, 3, 14))
        assert registry.get("lab").is_workday(date(2025, 3, 16))  # Sunday works


class TestWallDeadline:
    NY = ZoneInfo("America/New_York")
    HK = ZoneInfo("Asia/Hong_Kong")

    def test_instant_resolves_through_region_offset(self):
        deadline = WallDeadline(day="2025-03-14", hour=17, minute=0, region_tz="America/New_York")
        instant = deadline.instant()
        assert instant.utcoffset() == timedelta(hours=-4)  # EDT
        assert instant.astimezone(UTC) == datetime(2025, 3, 14, 21, 0, tzinfo=UTC)

    def test_offset_shifts_across_dst_boundary(self):
        before = WallDeadline("2025-03-08", 17, 0, "America/New_York")  # EST
        after = WallDeadline("2025-03-09", 17, 0, "America/New_York")  # EDT
        assert before.instant().utcoffset() == timedelta(hours=-5)
        assert after.instant().utcoffset() == timedelta(hours=-4)

    def test_overdue_checked_from_another_timezone(self):
        deadline = WallDeadline("2025-03-14", 17, 0, "America/New_York")
        # 2025-03-15 06:00 in Hong Kong == 2025-03-14 18:00 EDT -> overdue
        now_hk = datetime(2025, 3, 15, 6, 0, tzinfo=self.HK)
        assert deadline.is_overdue(now_hk)
        # 2025-03-15 04:00 in Hong Kong == 2025-03-14 16:00 EDT -> not yet
        assert not deadline.is_overdue(datetime(2025, 3, 15, 4, 0, tzinfo=self.HK))

    def test_grace_window(self):
        deadline = WallDeadline("2025-03-14", 17, 0, "America/New_York")
        now = datetime(2025, 3, 14, 18, 0, tzinfo=self.NY)
        assert deadline.is_overdue(now)
        assert not deadline.is_overdue(now, grace_hours=2.0)

    def test_naive_now_is_rejected(self):
        deadline = WallDeadline("2025-03-14", 17, 0, "America/New_York")
        with pytest.raises(ValueError, match="timezone-aware"):
            deadline.is_overdue(datetime(2025, 3, 14, 18, 0))

    def test_rolled_to_workday_skips_weekend_and_holidays(self):
        registry = CalendarRegistry.with_defaults()
        # Saturday 2025-03-15 -> Monday 2025-03-17
        saturday = WallDeadline("2025-03-15", 9, 0, "Asia/Hong_Kong")
        rolled = saturday.rolled_to_workday(registry.get("hk"))
        assert rolled.day == "2025-03-17"
        assert (rolled.hour, rolled.minute) == (9, 0)
        # Good Friday 2025-04-18 in DE -> Tuesday 2025-04-22 (Mon is Easter)
        friday = WallDeadline("2025-04-18", 12, 0, "Europe/Berlin")
        assert friday.rolled_to_workday(registry.get("de")).day == "2025-04-22"

    def test_region_helper_and_unknown_region(self):
        deadline = wall_deadline_in("us", "2025-07-03")
        assert deadline.region_tz == "America/New_York"
        assert (deadline.hour, deadline.minute) == (17, 0)
        with pytest.raises(ValueError, match="unknown calendar region"):
            wall_deadline_in("fr", "2025-07-03")
