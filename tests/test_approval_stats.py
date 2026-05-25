"""Per-approver outcome breakdowns."""

from datetime import UTC, datetime, timedelta

from mnemofold.approvals import (
    ApprovalQueue,
    ApprovalRequest,
    ApprovalStatus,
    Approver,
    ApproverPersona,
)

NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def request(rid: str, approver: str, **kwargs) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=rid,
        item_id=f"item-{rid}",
        item_kind="playbook_run",
        summary="s",
        requester="ana",
        approver=approver,
        created_at=NOW,
        **kwargs,
    )


class TestStatsByApprover:
    def test_empty_queue(self):
        assert ApprovalQueue().stats_by_approver() == {}

    def test_registered_approvers_appear_even_when_idle(self):
        queue = ApprovalQueue()
        queue.add_approver(Approver(name="boss", persona=ApproverPersona.ASK))
        assert queue.stats_by_approver() == {"boss": {}}

    def test_status_breakdown(self):
        queue = ApprovalQueue()
        queue.add_approver(Approver(name="boss"))
        queue.submit(request("r1", "boss"))
        queue.submit(request("r2", "boss"))
        queue.submit(request("r3", "boss"))
        queue.decide("r1", True, NOW)
        queue.decide("r2", False, NOW)
        queue.tick_expirations(NOW + timedelta(hours=1))  # r3 has no expiry
        stats = queue.stats_by_approver()
        assert stats["boss"]["approved"] == 1
        assert stats["boss"]["denied"] == 1
        assert stats["boss"]["pending"] == 1

    def test_escalations_counted_for_source(self):
        queue = ApprovalQueue()
        queue.add_approver(Approver(name="boss", escalation_to="cto"))
        queue.add_approver(Approver(name="cto"))
        queue.submit(
            request(
                "r1", "boss", expires_after=timedelta(hours=1), escalation_chain=["boss", "cto"]
            )
        )
        queue.escalate("r1", NOW)
        stats = queue.stats_by_approver()
        assert stats["boss"] == {"escalated_away": 1}
        assert stats["cto"] == {"pending": 1}

    def test_unregistered_approver_still_reported(self):
        queue = ApprovalQueue()
        queue.submit(request("r1", "ghost"))
        assert queue.stats_by_approver() == {"ghost": {"pending": 1}}

    def test_expired_status_counted(self):
        queue = ApprovalQueue()
        queue.submit(request("r1", "boss", expires_after=timedelta(minutes=5)))
        queue.tick_expirations(NOW + timedelta(minutes=10))
        stats = queue.stats_by_approver()
        assert stats["boss"]["expired"] == 1
        assert queue.requests[0].status == ApprovalStatus.EXPIRED

    def test_deterministic_key_order(self):
        queue = ApprovalQueue()
        for name in ("zoe", "ana", "mid"):
            queue.add_approver(Approver(name=name))
        assert list(queue.stats_by_approver()) == ["ana", "mid", "zoe"]
