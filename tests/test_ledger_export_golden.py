"""Golden bytes for CommitmentLedger.to_json.

The export covers commitments (sorted by id, tags sorted, floats
quantized) AND the full transition history, so any change to either
serialization is a deliberate, reviewed drift.
"""

import json
from pathlib import Path

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

FIXTURE = Path(__file__).parent / "fixtures" / "ledger_export_golden.json"


def make_ledger() -> CommitmentLedger:
    ledger = CommitmentLedger()
    ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft spec",
            due_date="2026-03-05T17:00:00+00:00",
            priority=0.7,
            grace_hours=2.0,
            created_at="2026-03-01T09:00:00+00:00",
            source_event_ids=["evt_a"],
            tags={"urgent", "review"},
            metadata={"channel": "mail"},
        )
    )
    ledger.add(
        Commitment(
            commitment_id="c2",
            owed_by="bo",
            owed_to="ana",
            description="review spec",
            due_date="2026-03-06T17:00:00+00:00",
            created_at="2026-03-02T09:00:00+00:00",
        )
    )
    assert ledger.transition("c2", CommitmentStatus.DONE, "2026-03-04T10:00:00+00:00")
    return ledger


class TestLedgerGolden:
    def test_export_matches_golden_bytes(self):
        assert make_ledger().to_json() == FIXTURE.read_text(encoding="utf-8")

    def test_commitments_sorted_and_tags_ordered(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert [c["commitment_id"] for c in payload["commitments"]] == ["c1", "c2"]
        assert payload["commitments"][0]["tags"] == ["review", "urgent"]

    def test_history_captures_creation_and_transition(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        actions = [(h["commitment_id"], h["action"]) for h in payload["history"]]
        assert actions == [("c1", "created"), ("c2", "created"), ("c2", "status_change")]

    def test_from_json_restores_commitments(self):
        loaded = CommitmentLedger.from_json(FIXTURE.read_text(encoding="utf-8"))
        original = json.loads(make_ledger().to_json())
        restored = json.loads(loaded.to_json())
        assert restored["commitments"] == original["commitments"]
        assert loaded.total_count() == 2

    def test_regeneration_is_stable(self):
        assert make_ledger().to_json() == make_ledger().to_json()
