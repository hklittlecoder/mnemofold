"""Tests for the temporal model module."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mnemofold.temporal import (
    IntervalFact,
    TemporalStore,
    WorkdayCalendar,
    deadline_overdue,
    time_until_deadline,
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
