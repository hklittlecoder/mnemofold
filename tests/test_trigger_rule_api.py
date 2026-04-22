"""Rule replacement and removal keep cooldown/dedupe memory intact."""

from datetime import UTC, datetime, timedelta

from mnemofold.triggers import (
    TriggerEngine,
    TriggerKind,
    TriggerRule,
    TriggerSeverity,
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


class TestRuleApi:
    def test_remove_rule(self):
        engine = TriggerEngine()
        engine.add_rule(rule("r1"))
        engine.add_rule(rule("r2", "t2"))
        assert engine.remove_rule("r1")
        assert not engine.remove_rule("r1")
        assert [r.rule_id for r in engine.rules()] == ["r2"]

    def test_replace_swaps_the_whole_set(self):
        engine = TriggerEngine()
        engine.add_rule(rule("old"))
        engine.replace_rules([rule("a"), rule("b", "t2")])
        assert [r.rule_id for r in engine.rules()] == ["a", "b"]

    def test_replace_with_empty_clears(self):
        engine = TriggerEngine()
        engine.add_rule(rule("r1"))
        engine.replace_rules([])
        assert engine.rules() == []
        assert engine.tick(NOW) == []

    def test_cooldown_survives_replacement(self):
        engine = TriggerEngine()
        engine.replace_rules([rule("r1")])
        first = engine.tick(NOW)
        assert len(first) == 1
        # re-derive the same rule set — cooldown memory must persist
        engine.replace_rules([rule("r1")])
        assert engine.tick(NOW + timedelta(hours=1)) == []
        again = engine.tick(NOW + timedelta(hours=13))
        assert len(again) == 1

    def test_removed_rule_stops_firing_but_keeps_memory(self):
        engine = TriggerEngine()
        engine.add_rule(rule("r1"))
        engine.tick(NOW)
        engine.remove_rule("r1")
        assert engine.tick(NOW + timedelta(hours=13)) == []
        # re-adding inside the old cooldown window stays quiet
        engine.add_rule(rule("r1"))
        assert engine.tick(NOW + timedelta(hours=11)) == []
        # ... and after the window it may fire again
        assert len(engine.tick(NOW + timedelta(hours=25))) == 1
