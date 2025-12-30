"""Workday arithmetic against merged 2025+2026 regional calendars."""

from datetime import date

from mnemofold.temporal import CalendarRegistry, wall_deadline_in

REGISTRY = CalendarRegistry.with_defaults(years=(2025, 2026))


class TestMultiYearArithmetic:
    def test_add_workdays_skips_thanksgiving_2026(self):
        us = REGISTRY.get("us")
        # Wed 2026-11-25 + 2 workdays: Thu 26 is a holiday, Fri 27 counts,
        # weekend passes, Mon 30 is the second
        assert us.add_workdays(date(2026, 11, 25), 2) == date(2026, 11, 30)

    def test_workdays_between_counts_around_holidays(self):
        us = REGISTRY.get("us")
        # Mon 2026-02-16 (holiday) .. Fri 2026-02-20 exclusive of Sat/Sun
        assert us.workdays_between(date(2026, 2, 16), date(2026, 2, 23)) == 4

    def test_lunar_new_year_blocks_hk_week(self):
        hk = REGISTRY.get("hk")
        for day in (17, 18, 19):
            assert not hk.is_workday(date(2026, 2, day))
        assert hk.next_workday(date(2026, 2, 17)) == date(2026, 2, 20)

    def test_german_movable_holidays_2026(self):
        de = REGISTRY.get("de")
        assert not de.is_workday(date(2026, 4, 3))  # Good Friday
        assert not de.is_workday(date(2026, 5, 14))  # Ascension
        assert de.add_workdays(date(2026, 5, 13), 1) == date(2026, 5, 15)

    def test_wall_deadline_rolls_over_observed_holiday_weekend(self):
        # Fri 2026-07-03 is the observed Independence Day holiday in the
        # merged US calendar; rolling forward lands on Monday 2026-07-06
        deadline = wall_deadline_in("us", "2026-07-03", 17)
        rolled = deadline.rolled_to_workday(REGISTRY.get("us"))
        assert rolled.day == "2026-07-06"
        assert rolled.hour == 17 and rolled.region_tz == deadline.region_tz

    def test_negative_add_workdays_crosses_year_boundary(self):
        us = REGISTRY.get("us")
        # Fri 2026-01-02 - 1 workday: Jan 1 is a holiday -> Wed 2025-12-31
        assert us.add_workdays(date(2026, 1, 2), -1) == date(2025, 12, 31)
