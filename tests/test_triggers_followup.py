"""Follow-up derivation: question-mark heuristic and its boundaries."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventType
from mnemofold.triggers import (
    TriggerKind,
    TriggerSeverity,
    derive_followup_rules,
    derive_stale_thread_rules,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def mail(tid: str, age_hours: float, *, subject: str = "s", body: str = "b") -> Event:
    return Event(
        event_type=EventType.MAIL_RECEIVED,
        timestamp=NOW - timedelta(hours=age_hours),
        content={"thread_id": tid, "subject": subject, "body": body},
    )


class TestDeriveFollowupRules:
    def test_unanswered_ask_yields_info_rule(self):
        rules = derive_followup_rules([mail("t1", 25, body="can you ship this?")], NOW)
        assert len(rules) == 1
        rule = rules[0]
        assert rule.rule_id == "trg-followup-t1"
        assert rule.kind == TriggerKind.FOLLOW_UP
        assert rule.severity == TriggerSeverity.INFO
        assert rule.fire_at == NOW

    def test_question_in_subject_counts(self):
        rules = derive_followup_rules([mail("t1", 30, subject="ETA?")], NOW)
        assert len(rules) == 1

    def test_boundary_at_unanswered_after(self):
        assert derive_followup_rules([mail("t1", 24, body="ok?")], NOW)
        assert not derive_followup_rules([mail("t1", 23.9, body="ok?")], NOW)

    def test_answered_thread_yields_nothing(self):
        events = [mail("t1", 48, body="can you ship this?"), mail("t1", 1, body="shipped.")]
        assert derive_followup_rules(events, NOW) == []

    def test_no_question_no_rule(self):
        assert derive_followup_rules([mail("t1", 48, body="statement.")], NOW) == []

    def test_keyless_events_ignored(self):
        note = Event(
            event_type=EventType.NOTE,
            timestamp=NOW - timedelta(hours=48),
            content={"title": "why? nobody knows"},
        )
        assert derive_followup_rules([note], NOW) == []

    def test_custom_window(self):
        rules = derive_followup_rules([mail("t1", 5, body="ok?")], NOW, unanswered_after_hours=4.0)
        assert len(rules) == 1

    def test_naive_now_treated_as_utc(self):
        rules = derive_followup_rules([mail("t1", 25, body="ok?")], datetime(2026, 3, 10, 10, 0))
        assert rules[0].fire_at == NOW


class TestStaleAndFollowupCoexistence:
    def test_same_thread_can_yield_both_kinds(self):
        events = [mail("t1", 96, body="any update on the release?")]
        stale = derive_stale_thread_rules(events, NOW)
        follow = derive_followup_rules(events, NOW)
        assert len(stale) == 1 and len(follow) == 1
        assert stale[0].rule_id != follow[0].rule_id
        assert {stale[0].kind, follow[0].kind} == {
            TriggerKind.STALE_THREAD,
            TriggerKind.FOLLOW_UP,
        }

    def test_derivation_is_input_order_independent(self):
        events = [
            mail("t1", 96, body="any update?"),
            mail("t2", 50, body="ping?"),
            mail("t1", 100, body="older"),
            mail("t3", 2, body="fresh"),
        ]
        forward = derive_followup_rules(events, NOW)
        backward = derive_followup_rules(list(reversed(events)), NOW)
        assert forward == backward
        assert [r.rule_id for r in forward] == ["trg-followup-t1", "trg-followup-t2"]
