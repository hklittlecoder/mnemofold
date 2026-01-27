"""Persisted trigger logs must survive rebuilds byte-for-byte."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventType
from mnemofold.triggers import (
    TriggerEngine,
    derive_followup_rules,
    derive_stale_thread_rules,
    fired_to_dict,
    read_trigger_log,
    write_trigger_log,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def build_fired():
    events = [
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=NOW - timedelta(days=4),
            content={"thread_id": "t1", "subject": "release", "body": "any update?"},
        ),
        Event(
            event_type=EventType.CHAT_MESSAGE,
            timestamp=NOW - timedelta(days=5),
            content={"thread_id": "t2", "body": "standup notes"},
        ),
    ]
    engine = TriggerEngine()
    for rule in derive_stale_thread_rules(events, NOW) + derive_followup_rules(events, NOW):
        engine.add_rule(rule)
    return engine.tick(NOW)


class TestTriggerLogBytes:
    def test_two_rebuilds_write_identical_files(self, tmp_path):
        first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        write_trigger_log(first, build_fired())
        write_trigger_log(second, build_fired())
        assert first.read_bytes() == second.read_bytes()

    def test_roundtrip_preserves_fields(self, tmp_path):
        fired = build_fired()
        path = tmp_path / "log.jsonl"
        write_trigger_log(path, fired)
        loaded = read_trigger_log(path)
        assert [(f.rule_id, f.kind, f.severity, f.suppressed) for f in loaded] == [
            (f.rule_id, f.kind, f.severity, f.suppressed) for f in fired
        ]
        assert [f.message for f in loaded] == [f.message for f in fired]

    def test_fired_to_dict_shape(self):
        fired = build_fired()
        payload = fired_to_dict(fired[0])
        assert set(payload) >= {
            "rule_id",
            "kind",
            "target_id",
            "fired_at",
            "severity",
            "message",
            "suppressed",
        }

    def test_log_covers_every_derived_rule(self, tmp_path):
        fired = build_fired()
        kinds = sorted(f.kind.value for f in fired)
        # t1: stale + follow-up; t2: stale only (no question in body)
        assert kinds == ["follow_up", "stale_thread", "stale_thread"]
        path = tmp_path / "log.jsonl"
        write_trigger_log(path, fired)
        assert len(read_trigger_log(path)) == 3
