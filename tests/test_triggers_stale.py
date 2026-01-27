"""Stale-thread rule derivation boundaries."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventType
from mnemofold.triggers import (
    TriggerKind,
    TriggerSeverity,
    derive_stale_thread_rules,
    thread_activity,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def thread_events(tid: str, ages_days: list[float]) -> list[Event]:
    return [
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=NOW - timedelta(days=age),
            content={"thread_id": tid, "subject": f"mail {age}"},
        )
        for age in ages_days
    ]


class TestThreadActivity:
    def test_groups_and_orders_events(self):
        events = thread_events("t1", [1.0, 3.0, 2.0])
        activity = thread_activity(events)
        assert list(activity) == ["t1"]
        stamps = [e.timestamp for e in activity["t1"]]
        assert stamps == sorted(stamps)

    def test_keyless_events_ignored(self):
        note = Event(event_type=EventType.NOTE, timestamp=NOW, content={"title": "no thread"})
        assert thread_activity([note]) == {}

    def test_non_string_ids_normalized(self):
        event = Event(event_type=EventType.MAIL_RECEIVED, timestamp=NOW, content={"thread_id": 42})
        assert list(thread_activity([event])) == ["42"]


class TestDeriveStaleThreadRules:
    def test_fresh_thread_yields_nothing(self):
        assert derive_stale_thread_rules(thread_events("t1", [1.0]), NOW) == []

    def test_stale_thread_yields_warning_rule(self):
        rules = derive_stale_thread_rules(thread_events("t1", [4.0]), NOW)
        assert len(rules) == 1
        rule = rules[0]
        assert rule.rule_id == "trg-thread-t1"
        assert rule.kind == TriggerKind.STALE_THREAD
        assert rule.severity == TriggerSeverity.WARNING
        assert rule.fire_at == NOW
        assert rule.target_id == "t1"

    def test_boundary_at_stale_after(self):
        assert derive_stale_thread_rules(thread_events("t1", [3.0]), NOW)
        assert not derive_stale_thread_rules(thread_events("t1", [2.99]), NOW)

    def test_boundary_at_closed_after(self):
        assert not derive_stale_thread_rules(thread_events("t1", [6.0]), NOW)
        assert derive_stale_thread_rules(thread_events("t1", [5.9]), NOW)

    def test_custom_windows(self):
        events = thread_events("t1", [1.5])
        rules = derive_stale_thread_rules(events, NOW, stale_after_days=1.0, closed_after_days=2.0)
        assert len(rules) == 1
        assert not derive_stale_thread_rules(
            thread_events("t1", [2.5]), NOW, stale_after_days=1.0, closed_after_days=2.0
        )

    def test_most_recent_event_wins(self):
        events = thread_events("t1", [10.0, 4.0])
        rules = derive_stale_thread_rules(events, NOW)
        assert len(rules) == 1
        assert "4.0 days" in rules[0].message

    def test_keyless_events_ignored(self):
        note = Event(
            event_type=EventType.NOTE,
            timestamp=NOW - timedelta(days=9),
            content={"title": "old note"},
        )
        assert derive_stale_thread_rules([note], NOW) == []

    def test_naive_now_treated_as_utc(self):
        naive = datetime(2026, 3, 10, 10, 0)
        rules = derive_stale_thread_rules(thread_events("t1", [4.0]), naive)
        assert len(rules) == 1
        assert rules[0].fire_at == NOW

    def test_rules_sorted_and_deterministic(self):
        events = (
            thread_events("t3", [4.0]) + thread_events("t1", [4.0]) + thread_events("t2", [4.0])
        )
        first = derive_stale_thread_rules(events, NOW)
        second = derive_stale_thread_rules(list(reversed(events)), NOW)
        assert [r.rule_id for r in first] == ["trg-thread-t1", "trg-thread-t2", "trg-thread-t3"]
        assert first == second

    def test_cooldown_and_dedupe_set(self):
        rule = derive_stale_thread_rules(thread_events("t1", [4.0]), NOW)[0]
        assert rule.cooldown == timedelta(hours=24)
        assert rule.dedupe_window == timedelta(hours=24)
