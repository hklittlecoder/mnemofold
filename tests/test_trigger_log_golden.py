"""Golden bytes for the chained trigger log.

The fixture is written from the same two fired triggers the test builds
(one active, one suppressed by quiet hours); any change to entry
serialization or the chain-hash construction fails here deliberately.
"""

from datetime import UTC, datetime
from pathlib import Path

from mnemofold.triggers import (
    FiredTrigger,
    TriggerKind,
    TriggerSeverity,
    read_trigger_log,
    write_trigger_log,
)

FIXTURE = Path(__file__).parent / "fixtures" / "trigger_log_golden.jsonl"
NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def make_fired() -> list[FiredTrigger]:
    return [
        FiredTrigger(
            rule_id="trg-thread-t1",
            kind=TriggerKind.STALE_THREAD,
            target_id="t1",
            fired_at=NOW,
            severity=TriggerSeverity.WARNING,
            message="thread t1 quiet since 2026-03-06T10:00:00+00:00 (4.0 days)",
        ),
        FiredTrigger(
            rule_id="trg-followup-t1",
            kind=TriggerKind.FOLLOW_UP,
            target_id="t1",
            fired_at=NOW,
            severity=TriggerSeverity.INFO,
            message="thread t1 ends in an unanswered ask",
            suppressed=True,
            suppress_reason="quiet_hours",
        ),
    ]


class TestTriggerLogGolden:
    def test_write_matches_golden_bytes(self, tmp_path):
        path = tmp_path / "log.jsonl"
        write_trigger_log(path, make_fired())
        assert path.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    def test_golden_reads_back(self):
        loaded = read_trigger_log(FIXTURE)
        assert [(f.rule_id, f.kind, f.suppressed) for f in loaded] == [
            (f.rule_id, f.kind, f.suppressed) for f in make_fired()
        ]

    def test_regeneration_is_stable(self, tmp_path):
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        write_trigger_log(a, make_fired())
        write_trigger_log(b, make_fired())
        assert a.read_bytes() == b.read_bytes() == FIXTURE.read_bytes()
