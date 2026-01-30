"""Due-time aging buckets over a planted ledger."""

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

NOW = "2026-03-10T12:00:00+00:00"


def commit(cid, due, *, status=CommitmentStatus.OPEN, grace=0.0) -> Commitment:
    return Commitment(
        commitment_id=cid,
        owed_by="ana",
        owed_to="bo",
        description=f"task {cid}",
        due_date=due,
        status=status,
        grace_hours=grace,
    )


def make_ledger() -> CommitmentLedger:
    ledger = CommitmentLedger()
    ledger.add(commit("c_over", "2026-03-09T12:00:00+00:00"))
    ledger.add(commit("c_grace", "2026-03-10T11:00:00+00:00", grace=2.0))
    ledger.add(commit("c_today", "2026-03-10T23:00:00+00:00"))
    ledger.add(commit("c_week", "2026-03-13T12:00:00+00:00"))
    ledger.add(commit("c_later", "2026-03-25T12:00:00+00:00"))
    ledger.add(commit("c_nodue", "not-a-date"))
    ledger.add(commit("c_done", "2026-03-09T12:00:00+00:00", status=CommitmentStatus.DONE))
    return ledger


class TestAgingReport:
    def test_buckets_are_correct(self):
        report = make_ledger().aging_report(NOW)
        assert report["overdue"] == ["c_over"]
        assert report["due_today"] == ["c_grace", "c_today"]
        assert report["due_this_week"] == ["c_week"]
        assert report["later"] == ["c_later"]
        assert report["no_due"] == ["c_nodue"]

    def test_counts_sum_to_active_total(self):
        report = make_ledger().aging_report(NOW)
        assert report["total_active"] == 6  # c_done excluded
        assert sum(report["counts"].values()) == 6
        assert report["counts"]["due_today"] == 2

    def test_terminal_statuses_excluded(self):
        ledger = CommitmentLedger()
        ledger.add(commit("c1", "2026-03-09T12:00:00+00:00", status=CommitmentStatus.CANCELLED))
        report = ledger.aging_report(NOW)
        assert report["total_active"] == 0
        assert report["overdue"] == []

    def test_report_is_deterministic(self):
        assert make_ledger().aging_report(NOW) == make_ledger().aging_report(NOW)

    def test_now_is_echoed(self):
        assert make_ledger().aging_report(NOW)["now"] == NOW
