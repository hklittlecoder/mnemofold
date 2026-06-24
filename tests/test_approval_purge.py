"""Purging expired approvals is precise and leaves other states alone."""

from datetime import UTC, datetime, timedelta

from mnemofold.approvals import (
    ApprovalQueue,
    ApprovalRequest,
    ApprovalStatus,
)

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def request(rid: str, expires: bool = True) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=rid,
        item_id=f"item-{rid}",
        item_kind="playbook_run",
        summary="s",
        requester="ana",
        approver="boss",
        created_at=NOW,
        expires_after=timedelta(hours=1) if expires else None,
    )


class TestPurgeExpired:
    def test_purge_removes_only_expired(self):
        queue = ApprovalQueue()
        queue.submit(request("r1"))
        queue.submit(request("r2", expires=False))
        queue.decide("r2", True, NOW)
        queue.tick_expirations(NOW + timedelta(hours=2))
        assert queue.requests[0].status == ApprovalStatus.EXPIRED
        removed = queue.purge_expired()
        assert removed == 1
        assert [r.request_id for r in queue.requests] == ["r2"]

    def test_pending_past_due_survives_purge(self):
        queue = ApprovalQueue()
        queue.submit(request("r1"))
        # no tick: still PENDING even though past its deadline
        assert queue.purge_expired() == 0
        assert len(queue.requests) == 1

    def test_double_purge_is_a_noop(self):
        queue = ApprovalQueue()
        queue.submit(request("r1"))
        queue.tick_expirations(NOW + timedelta(hours=2))
        assert queue.purge_expired() == 1
        assert queue.purge_expired() == 0

    def test_metrics_reflect_purge(self):
        queue = ApprovalQueue()
        queue.submit(request("r1"))
        queue.submit(request("r2", expires=False))
        queue.tick_expirations(NOW + timedelta(hours=2))
        before = queue.audit_metrics()
        assert before["expired"] == 1
        assert before["pending"] == 1
        queue.purge_expired()
        after = queue.audit_metrics()
        assert after.get("expired", 0) == 0
        assert after["pending"] == 1

    def test_serialization_shrinks_with_queue(self):
        queue = ApprovalQueue()
        queue.submit(request("r1"))
        queue.tick_expirations(NOW + timedelta(hours=2))
        queue.purge_expired()
        assert queue.to_dict()["requests"] == []
