"""Both derived rules for one thread fire independently, then dedupe."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventType
from mnemofold.triggers import (
    TriggerEngine,
    derive_followup_rules,
    derive_stale_thread_rules,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def build_engine() -> TriggerEngine:
    events = [
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=NOW - timedelta(days=4),
            content={"thread_id": "t1", "subject": "release", "body": "any update?"},
        ),
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=NOW - timedelta(days=1),
            content={"thread_id": "t2", "subject": "fresh", "body": "no question"},
        ),
    ]
    engine = TriggerEngine()
    for rule in derive_stale_thread_rules(events, NOW) + derive_followup_rules(events, NOW):
        engine.add_rule(rule)
    return engine


class TestDerivedMix:
    def test_only_stale_and_followup_for_t1_fire(self):
        engine = build_engine()
        fired = engine.tick(NOW)
        assert sorted(f.rule_id for f in fired) == ["trg-followup-t1", "trg-thread-t1"]
        assert all(not f.suppressed for f in fired)

    def test_dedupe_is_per_kind(self):
        engine = build_engine()
        engine.tick(NOW)
        # within the shared 24h cooldown both rules stay silent
        assert engine.tick(NOW + timedelta(hours=2)) == []
        # after the window both may fire again
        again = engine.tick(NOW + timedelta(hours=25))
        assert sorted(f.rule_id for f in again) == ["trg-followup-t1", "trg-thread-t1"]

    def test_counts_by_kind_after_fire(self):
        engine = build_engine()
        engine.tick(NOW)
        assert engine.counts_by_kind() == {"stale_thread": 1, "follow_up": 1}

    def test_active_triggers_lists_both(self):
        engine = build_engine()
        engine.tick(NOW)
        assert len(engine.active_triggers()) == 2
