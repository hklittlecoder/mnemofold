"""2026 holiday tables: golden freeze plus registry behavior."""

import json
from datetime import date
from pathlib import Path

import pytest

from mnemofold.temporal import HOLIDAYS_BY_YEAR, CalendarRegistry

FIXTURE = Path(__file__).parent / "fixtures" / "calendar_holidays_2026_golden.json"


class TestHolidayTables:
    def test_table_matches_golden_fixture(self):
        frozen = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert set(frozen) == set(HOLIDAYS_BY_YEAR[2026])
        for region, days in frozen.items():
            assert sorted(HOLIDAYS_BY_YEAR[2026][region]) == days

    def test_both_years_registered(self):
        assert set(HOLIDAYS_BY_YEAR) == {2025, 2026}

    def test_movable_2026_dates(self):
        us = HOLIDAYS_BY_YEAR[2026]["us"]
        assert "2026-11-26" in us  # 4th Thursday of November
        assert "2026-07-03" in us  # July 4 falls on a Saturday
        de = HOLIDAYS_BY_YEAR[2026]["de"]
        assert "2026-04-03" in de  # Good Friday (Easter Sunday: April 5)
        assert "2026-05-25" in de  # Whit Monday
        hk = HOLIDAYS_BY_YEAR[2026]["hk"]
        assert {"2026-02-17", "2026-02-18", "2026-02-19"} <= hk  # Lunar New Year


class TestYearAwareRegistry:
    def test_default_still_covers_2025_only(self):
        registry = CalendarRegistry.with_defaults()
        us = registry.get("us")
        assert not us.is_workday(date(2025, 11, 27))  # Thanksgiving 2025
        assert us.is_workday(date(2026, 11, 26))  # 2026 table not merged

    def test_multi_year_merge(self):
        registry = CalendarRegistry.with_defaults(years=(2025, 2026))
        us = registry.get("us")
        assert not us.is_workday(date(2025, 11, 27))
        assert not us.is_workday(date(2026, 11, 26))
        assert us.is_workday(date(2026, 11, 25))

    def test_single_year_selection(self):
        registry = CalendarRegistry.with_defaults(years=(2026,))
        de = registry.get("de")
        assert not de.is_workday(date(2026, 10, 3))
        assert de.is_workday(date(2025, 10, 3))  # 2025 table not merged

    def test_unknown_year_raises(self):
        with pytest.raises(KeyError, match="2027"):
            CalendarRegistry.with_defaults(years=(2025, 2027))

    def test_regions_unchanged_by_year_selection(self):
        assert CalendarRegistry.with_defaults(years=(2026,)).regions() == ["de", "hk", "us"]
