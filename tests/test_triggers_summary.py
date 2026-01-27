"""Scheduled daily/weekly summary rule derivation."""

from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.triggers import TriggerEngine, TriggerKind, derive_summary_rules

# Tuesday 2026-03-10 10:00 UTC
NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


class TestDeriveSummaryRules:
    def test_default_counts_and_kinds(self):
        rules = derive_summary_rules(NOW)
        kinds = [r.kind for r in rules]
        assert kinds.count(TriggerKind.DAILY_SUMMARY) == 3
        assert kinds.count(TriggerKind.WEEKLY_REVIEW) == 2

    def test_daily_starts_today_when_hour_ahead(self):
        rules = derive_summary_rules(NOW, daily_count=2, weekly_count=0)
        dailies = [r for r in rules if r.kind == TriggerKind.DAILY_SUMMARY]
        assert dailies[0].fire_at == datetime(2026, 3, 10, 17, 0, tzinfo=UTC)
        assert dailies[1].fire_at == datetime(2026, 3, 11, 17, 0, tzinfo=UTC)

    def test_daily_skips_today_when_hour_passed(self):
        late = datetime(2026, 3, 10, 18, 0, tzinfo=UTC)
        rules = derive_summary_rules(late, daily_count=1, weekly_count=0)
        assert rules[0].fire_at == datetime(2026, 3, 11, 17, 0, tzinfo=UTC)

    def test_weekly_finds_next_fridays(self):
        rules = derive_summary_rules(NOW, daily_count=0, weekly_count=2, weekly_weekday=4)
        fire_dates = [r.fire_at.date().isoformat() for r in rules]
        # next Fridays after Tue 2026-03-10 are 03-13 and 03-20
        assert fire_dates == ["2026-03-13", "2026-03-20"]

    def test_weekly_skips_passed_hour_on_matching_day(self):
        friday_evening = datetime(2026, 3, 13, 17, 0, tzinfo=UTC)
        rules = derive_summary_rules(
            friday_evening, daily_count=0, weekly_count=1, weekly_weekday=4
        )
        assert rules[0].fire_at.date().isoformat() == "2026-03-20"

    def test_ids_embed_fire_date(self):
        rules = derive_summary_rules(NOW, daily_count=1, weekly_count=1)
        ids = {r.rule_id for r in rules}
        assert "trg-daily-2026-03-10" in ids
        assert "trg-weekly-2026-03-13" in ids

    def test_rules_sorted_by_fire_time(self):
        rules = derive_summary_rules(NOW)
        stamps = [r.fire_at for r in rules]
        assert stamps == sorted(stamps)

    def test_zero_counts_yield_empty(self):
        assert derive_summary_rules(NOW, daily_count=0, weekly_count=0) == []

    def test_naive_now_treated_as_utc(self):
        naive = datetime(2026, 3, 10, 10, 0)
        assert derive_summary_rules(naive) == derive_summary_rules(NOW)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"daily_count": -1},
            {"weekly_count": -1},
            {"daily_hour": 24},
            {"daily_hour": -1},
            {"weekly_hour": 24},
            {"weekly_weekday": 7},
        ],
    )
    def test_invalid_arguments_raise(self, kwargs):
        with pytest.raises(ValueError):
            derive_summary_rules(NOW, **kwargs)

    def test_deterministic_across_calls(self):
        assert derive_summary_rules(NOW) == derive_summary_rules(NOW)

    def test_engine_fires_daily_rule_at_its_hour(self):
        engine = TriggerEngine()
        for rule in derive_summary_rules(NOW, daily_count=1, weekly_count=0):
            engine.add_rule(rule)
        assert engine.tick(NOW) == []
        fired = engine.tick(NOW + timedelta(hours=7))
        assert len(fired) == 1
        assert fired[0].kind == TriggerKind.DAILY_SUMMARY
