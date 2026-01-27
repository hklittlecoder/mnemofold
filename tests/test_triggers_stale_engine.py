"""Derived stale-thread rules under cooldown, quiet hours, and coverage."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventType
from mnemofold.triggers import (
    QuietHours,
    TriggerEngine,
    TriggerKind,
    derive_stale_thread_rules,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def stale_events() -> list[Event]:
    return [
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=NOW - timedelta(days=4),
            content={"thread_id": "t1", "subject": "old"},
        )
    ]


def engine_with_stale_rules(**kwargs) -> TriggerEngine:
    engine = TriggerEngine(**kwargs)
    for rule in derive_stale_thread_rules(stale_events(), NOW):
        engine.add_rule(rule)
    return engine


class TestStaleEngineIntegration:
    def test_rule_fires_on_tick(self):
        engine = engine_with_stale_rules()
        fired = engine.tick(NOW)
        assert len(fired) == 1
        assert fired[0].kind == TriggerKind.STALE_THREAD
        assert not fired[0].suppressed
        assert engine.counts_by_kind() == {"stale_thread": 1}

    def test_cooldown_blocks_second_tick(self):
        engine = engine_with_stale_rules()
        engine.tick(NOW)
        assert engine.tick(NOW + timedelta(hours=1)) == []
        again = engine.tick(NOW + timedelta(hours=25))
        assert len(again) == 1

    def test_quiet_hours_suppress_warning(self):
        engine = engine_with_stale_rules(quiet_hours=QuietHours(22, 7))
        fired = engine.tick(datetime(2026, 3, 10, 23, 0, tzinfo=UTC))
        assert len(fired) == 1
        assert fired[0].suppressed
        assert fired[0].suppress_reason == "quiet_hours"
        assert engine.active_triggers() == []

    def test_report_coverage_suppresses(self):
        engine = engine_with_stale_rules(
            is_covered_by_report=lambda tid, kind: tid == "t1" and kind == TriggerKind.STALE_THREAD
        )
        fired = engine.tick(NOW)
        assert fired[0].suppressed
        assert fired[0].suppress_reason == "covered_by_report"

    def test_not_due_before_fire_at(self):
        engine = engine_with_stale_rules()
        assert engine.tick(NOW - timedelta(minutes=5)) == []

    def test_summary_counts_suppression(self):
        engine = engine_with_stale_rules(quiet_hours=QuietHours(22, 7))
        engine.tick(datetime(2026, 3, 10, 23, 30, tzinfo=UTC))
        summary = engine.summary_report()
        assert summary["total_fired"] == 1
        assert summary["suppressed"] == 1
        assert summary["by_suppress_reason"] == {"quiet_hours": 1}
