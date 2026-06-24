"""Importing a persisted fire log restores session semantics."""

from datetime import UTC, datetime, timedelta

from mnemofold.triggers import (
    FiredTrigger,
    TriggerEngine,
    TriggerKind,
    TriggerRule,
    TriggerSeverity,
    read_trigger_log,
    write_trigger_log,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def rule(rule_id: str = "r1", target: str = "t1") -> TriggerRule:
    return TriggerRule(
        rule_id=rule_id,
        kind=TriggerKind.STALE_THREAD,
        target_id=target,
        fire_at=NOW,
        severity=TriggerSeverity.WARNING,
        cooldown=timedelta(hours=12),
        dedupe_window=timedelta(hours=12),
    )


def fired_entry(rule_id: str, target: str, when: datetime) -> FiredTrigger:
    return FiredTrigger(
        rule_id=rule_id,
        kind=TriggerKind.STALE_THREAD,
        target_id=target,
        fired_at=when,
        severity=TriggerSeverity.WARNING,
        message="test fire",
    )


class TestImportFired:
    def test_import_restores_summary(self):
        engine = TriggerEngine()
        engine.add_rule(rule())
        engine.tick(NOW)
        fresh = TriggerEngine()
        assert fresh.import_fired(engine.fired()) == 1
        assert fresh.summary_report() == engine.summary_report()

    def test_cooldown_clock_survives_via_file(self, tmp_path):
        first = TriggerEngine()
        first.add_rule(rule())
        first.tick(NOW)
        path = tmp_path / "log.jsonl"
        write_trigger_log(path, first.fired())

        restored = TriggerEngine()
        restored.import_fired(read_trigger_log(path))
        restored.add_rule(rule())
        assert restored.tick(NOW + timedelta(hours=1)) == []  # still cooling down
        assert len(restored.tick(NOW + timedelta(hours=13))) == 1

    def test_import_is_order_independent_for_clocks(self):
        early = fired_entry("r1", "t1", NOW)
        late = fired_entry("r1", "t1", NOW + timedelta(hours=5))
        a, b = TriggerEngine(), TriggerEngine()
        a.import_fired([early, late])
        b.import_fired([late, early])
        a.add_rule(rule())
        b.add_rule(rule())
        probe = NOW + timedelta(hours=6)
        assert a.tick(probe) == [] and b.tick(probe) == []  # 12h cooldown from NOW+5
        assert len(a.tick(NOW + timedelta(hours=18))) == 1

    def test_import_count_and_active_triggers(self):
        engine = TriggerEngine()
        entries = [fired_entry(f"r{i}", f"t{i}", NOW) for i in range(3)]
        assert engine.import_fired(entries) == 3
        assert len(engine.active_triggers()) == 3
