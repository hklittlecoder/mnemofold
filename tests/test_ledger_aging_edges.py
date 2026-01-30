"""Aging bucket boundaries: 24h, 7d, grace edges, and status coverage."""

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

NOW = "2026-03-10T12:00:00+00:00"


def single(due: str, *, status=CommitmentStatus.OPEN, grace: float = 0.0) -> dict:
    ledger = CommitmentLedger()
    ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="a",
            owed_to="b",
            description="d",
            due_date=due,
            status=status,
            grace_hours=grace,
        )
    )
    return ledger.aging_report(NOW)


def bucket_of(report: dict) -> str:
    for name in ("overdue", "due_today", "due_this_week", "later", "no_due"):
        if report[name]:
            return name
    raise AssertionError("commitment landed in no bucket")


class TestAgingBoundaries:
    def test_exactly_24h_is_this_week(self):
        assert bucket_of(single("2026-03-11T12:00:00+00:00")) == "due_this_week"

    def test_just_under_24h_is_today(self):
        assert bucket_of(single("2026-03-11T11:59:00+00:00")) == "due_today"

    def test_exactly_seven_days_is_later(self):
        assert bucket_of(single("2026-03-17T12:00:00+00:00")) == "later"

    def test_just_under_seven_days_is_this_week(self):
        assert bucket_of(single("2026-03-17T11:00:00+00:00")) == "due_this_week"

    def test_past_due_within_grace_is_due_today(self):
        report = single("2026-03-10T11:00:00+00:00", grace=2.0)
        assert bucket_of(report) == "due_today"

    def test_one_second_past_grace_is_overdue(self):
        report = single("2026-03-10T09:59:59+00:00", grace=2.0)
        assert bucket_of(report) == "overdue"

    def test_exactly_at_grace_edge_is_not_overdue(self):
        # due 10:00 + 2h grace = 12:00 == now; overdue requires now > due+grace
        report = single("2026-03-10T10:00:00+00:00", grace=2.0)
        assert bucket_of(report) == "due_today"

    def test_in_progress_counts_as_active(self):
        report = single("2026-03-25T12:00:00+00:00", status=CommitmentStatus.IN_PROGRESS)
        assert report["total_active"] == 1
        assert bucket_of(report) == "later"

    def test_superseded_excluded(self):
        report = single("2026-03-09T12:00:00+00:00", status=CommitmentStatus.SUPERSEDED)
        assert report["total_active"] == 0

    def test_empty_due_date_is_no_due(self):
        assert bucket_of(single("")) == "no_due"
