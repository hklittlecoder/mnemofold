"""Owner-grouped overdue views for standup-style reporting."""

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

NOW = "2026-03-10T12:00:00+00:00"


def commit(cid, owed_by, due, *, status=CommitmentStatus.OPEN, grace=0.0):
    return Commitment(
        commitment_id=cid,
        owed_by=owed_by,
        owed_to="team",
        description=f"task {cid}",
        due_date=due,
        status=status,
        grace_hours=grace,
        created_at="2026-03-01T09:00:00+00:00",
    )


class TestOverdueByPerson:
    def test_groups_and_sorts(self):
        ledger = CommitmentLedger()
        ledger.add(commit("b1", "bo", "2026-03-09T12:00:00+00:00"))
        ledger.add(commit("a2", "ana", "2026-03-08T12:00:00+00:00"))
        ledger.add(commit("a1", "ana", "2026-03-07T12:00:00+00:00"))
        grouped = ledger.overdue_by_person(NOW)
        assert grouped == {"ana": ["a1", "a2"], "bo": ["b1"]}

    def test_nothing_overdue(self):
        ledger = CommitmentLedger()
        ledger.add(commit("x", "ana", "2026-03-20T12:00:00+00:00"))
        assert ledger.overdue_by_person(NOW) == {}

    def test_terminal_statuses_excluded(self):
        ledger = CommitmentLedger()
        ledger.add(commit("d", "ana", "2026-03-09T12:00:00+00:00", status=CommitmentStatus.DONE))
        ledger.add(
            commit("c", "ana", "2026-03-09T12:00:00+00:00", status=CommitmentStatus.CANCELLED)
        )
        assert ledger.overdue_by_person(NOW) == {}

    def test_grace_honored(self):
        ledger = CommitmentLedger()
        ledger.add(commit("g", "ana", "2026-03-10T11:30:00+00:00", grace=2.0))
        assert ledger.overdue_by_person(NOW) == {}
        ledger.add(commit("h", "ana", "2026-03-10T09:00:00+00:00", grace=1.0))
        assert ledger.overdue_by_person(NOW) == {"ana": ["h"]}

    def test_aggregate_grace_override(self):
        ledger = CommitmentLedger()
        ledger.add(commit("g", "ana", "2026-03-10T11:30:00+00:00"))
        assert ledger.overdue_by_person(NOW) == {"ana": ["g"]}
        assert ledger.overdue_by_person(NOW, grace_hours=2.0) == {}
