"""Workload views: grouped overdue feeds standup lines and heat strips."""

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus
from mnemofold.review import StandupGenerator, render_work_strip_svg

NOW = "2026-03-10T12:00:00+00:00"


def ledger_with_overdue() -> CommitmentLedger:
    ledger = CommitmentLedger()
    ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft",
            due_date="2026-03-08T12:00:00+00:00",
            created_at="2026-03-01T09:00:00+00:00",
        )
    )
    ledger.add(
        Commitment(
            commitment_id="c2",
            owed_by="bo",
            owed_to="ana",
            description="review",
            due_date="2026-03-09T12:00:00+00:00",
            created_at="2026-03-01T09:00:00+00:00",
        )
    )
    ledger.add(
        Commitment(
            commitment_id="c3",
            owed_by="ana",
            owed_to="bo",
            description="ship",
            due_date="2026-03-20T12:00:00+00:00",
            created_at="2026-03-01T09:00:00+00:00",
        )
    )
    ledger.transition("c3", CommitmentStatus.DONE, "2026-03-09T18:00:00+00:00")
    return ledger


class TestStandupWorkload:
    def test_standup_lists_overdue_with_citations(self):
        data = StandupGenerator(ledger_with_overdue()).generate(NOW)
        joined = " ".join(data.overdue)
        assert "c1" in joined and "c2" in joined
        assert "c3" not in joined  # done commitments are not overdue

    def test_grouped_view_matches_flat_overdue(self):
        ledger = ledger_with_overdue()
        flat = {c.commitment_id for c in ledger.overdue(NOW)}
        grouped = {cid for ids in ledger.overdue_by_person(NOW).values() for cid in ids}
        assert flat == grouped

    def test_heat_strip_from_daily_overdue_counts(self):
        ledger = ledger_with_overdue()
        days = ["2026-03-08", "2026-03-09", "2026-03-10"]
        counts = [len(ledger.overdue(f"{day}T23:59:59+00:00")) for day in days]
        assert counts == sorted(counts)  # overdue sets only grow here
        svg = render_work_strip_svg(counts)
        assert svg.count("<rect") == len(days)
