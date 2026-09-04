"""Nudge semantics: kinds, grace windows, blocking, and ordering."""

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

NOW = "2026-03-10T12:00:00+00:00"


def commit(cid, due, *, status=CommitmentStatus.OPEN, grace=0.0, depends=None):
    return Commitment(
        commitment_id=cid,
        owed_by="ana",
        owed_to="bo",
        description=f"task {cid}",
        due_date=due,
        status=status,
        grace_hours=grace,
        depends_on=list(depends or []),
        created_at="2026-03-01T09:00:00+00:00",
    )


class TestNudgeEdges:
    def test_overdue_nudge(self):
        ledger = CommitmentLedger()
        ledger.add(commit("late", "2026-03-09T12:00:00+00:00"))
        nudges = ledger.nudges(NOW)
        assert [(n.commitment_id, n.kind) for n in nudges] == [("late", "overdue")]

    def test_grace_window_delays_overdue(self):
        ledger = CommitmentLedger()
        ledger.add(commit("g", "2026-03-10T11:30:00+00:00", grace=2.0))
        nudges = ledger.nudges(NOW, ahead_days=2.0)
        kinds = {n.commitment_id: n.kind for n in nudges}
        # inside its grace window the commitment is neither overdue nor upcoming
        assert "g" not in kinds

    def test_blocked_nudge(self):
        ledger = CommitmentLedger()
        # both due inside the ahead window; dep is still in progress so
        # "blocked" cannot be considered on track
        ledger.add(commit("dep", "2026-03-11T12:00:00+00:00"))
        ledger.add(commit("blocked", "2026-03-11T12:00:00+00:00", depends=["dep"]))
        ledger.transition("dep", CommitmentStatus.IN_PROGRESS, NOW)
        nudges = ledger.nudges(NOW)
        pairs = [(n.commitment_id, n.kind) for n in nudges]
        assert ("blocked", "blocked") in pairs
        assert ("dep", "upcoming") in pairs

    def test_terminal_statuses_never_nudged(self):
        ledger = CommitmentLedger()
        ledger.add(commit("done", "2026-03-09T12:00:00+00:00", status=CommitmentStatus.DONE))
        ledger.add(commit("gone", "2026-03-09T12:00:00+00:00", status=CommitmentStatus.CANCELLED))
        assert ledger.nudges(NOW) == []

    def test_sorted_by_due_then_id(self):
        ledger = CommitmentLedger()
        ledger.add(commit("b", "2026-03-11T09:00:00+00:00"))
        ledger.add(commit("a", "2026-03-11T09:00:00+00:00"))
        ledger.add(commit("c", "2026-03-10T18:00:00+00:00"))
        nudges = ledger.nudges(NOW, ahead_days=2.0)
        assert [n.commitment_id for n in nudges] == ["c", "a", "b"]
