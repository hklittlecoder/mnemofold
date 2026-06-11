"""The ledger must always agree with its own append-only history."""

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus


def make_ledger() -> CommitmentLedger:
    ledger = CommitmentLedger()
    ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft spec",
            due_date="2026-03-05T17:00:00+00:00",
            created_at="2026-03-01T09:00:00+00:00",
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


class TestVerifyHistory:
    def test_clean_ledger_is_consistent(self):
        report = make_ledger().verify_history()
        assert report["ok"] is True
        assert report["mismatches"] == []
        assert report["history_entries"] == 3
        assert report["replayed_statuses"] == {"c1": "open", "c2": "done"}

    def test_direct_state_mutation_is_caught(self):
        ledger = make_ledger()
        ledger.get("c1").status = CommitmentStatus.DONE  # bypasses transition()
        report = ledger.verify_history()
        assert report["ok"] is False
        assert report["mismatches"] == [
            {"commitment_id": "c1", "history_says": "open", "live": "done"}
        ]

    def test_removed_commitments_are_history_only(self):
        ledger = make_ledger()
        assert ledger.remove("c2")
        report = ledger.verify_history()
        assert report["ok"] is True
        assert report["history_only"] == ["c2"]

    def test_json_roundtrip_preserves_consistency(self):
        ledger = make_ledger()
        restored = CommitmentLedger.from_json(ledger.to_json())
        assert restored.verify_history()["ok"] is True

    def test_empty_ledger(self):
        report = CommitmentLedger().verify_history()
        assert report["ok"] is True
        assert report["history_entries"] == 0
