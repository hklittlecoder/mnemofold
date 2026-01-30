"""Burndown series computed from ledger creations and transitions."""

import pytest

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus


def commit(cid: str, created: str, *, status=CommitmentStatus.OPEN) -> Commitment:
    return Commitment(
        commitment_id=cid,
        owed_by="a",
        owed_to="b",
        description=f"task {cid}",
        due_date="2026-03-20T12:00:00+00:00",
        status=status,
        created_at=created,
    )


def make_ledger() -> CommitmentLedger:
    ledger = CommitmentLedger()
    ledger.add(commit("c1", "2026-02-27T09:00:00+00:00"))  # before start
    ledger.add(commit("c2", "2026-03-02T09:00:00+00:00"))
    ledger.add(commit("c3", ""))  # no created_at -> falls back to start day
    ledger.transition("c2", CommitmentStatus.DONE, "2026-03-03T10:00:00+00:00")
    return ledger


class TestBurndownSeries:
    def test_series_shape_and_days(self):
        series = make_ledger().burndown_series("2026-03-01", 4)
        assert [row["day"] for row in series] == [
            "2026-03-01",
            "2026-03-02",
            "2026-03-03",
            "2026-03-04",
        ]

    def test_created_counts_accumulate(self):
        series = make_ledger().burndown_series("2026-03-01", 4)
        # c1 (pre-start) + c3 (fallback) counted from day one; c2 joins 03-02
        assert [row["created"] for row in series] == [2, 3, 3, 3]

    def test_resolved_follows_transitions(self):
        series = make_ledger().burndown_series("2026-03-01", 4)
        assert [row["resolved"] for row in series] == [0, 0, 1, 1]

    def test_open_is_created_minus_resolved(self):
        for row in make_ledger().burndown_series("2026-03-01", 4):
            assert row["open"] == row["created"] - row["resolved"]

    def test_empty_ledger_is_all_zeros(self):
        series = CommitmentLedger().burndown_series("2026-03-01", 3)
        assert all(row["created"] == row["resolved"] == 0 for row in series)

    def test_zero_days(self):
        assert make_ledger().burndown_series("2026-03-01", 0) == []

    def test_negative_days_rejected(self):
        with pytest.raises(ValueError):
            make_ledger().burndown_series("2026-03-01", -1)

    def test_updated_at_fallback(self):
        ledger = CommitmentLedger()
        c = commit("c1", "")
        c.updated_at = "2026-03-02T18:00:00+00:00"
        ledger.add(c)
        series = ledger.burndown_series("2026-03-01", 3)
        assert [row["created"] for row in series] == [0, 1, 1]

    def test_deterministic(self):
        a = make_ledger().burndown_series("2026-03-01", 5)
        b = make_ledger().burndown_series("2026-03-01", 5)
        assert a == b
