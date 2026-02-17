"""Approval queue serialization roundtrips and reload behavior."""

from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.approvals import (
    ApprovalQueue,
    ApprovalRequest,
    ApprovalStatus,
    Approver,
    ApproverPersona,
)
from mnemofold.persist import PersistError


def build_queue() -> ApprovalQueue:
    queue = ApprovalQueue()
    queue.add_approver(Approver(name="boss", persona=ApproverPersona.ASK, escalation_to="auto"))
    queue.add_approver(Approver(name="auto", persona=ApproverPersona.AUTO_APPROVE))
    queue.submit(
        ApprovalRequest(
            request_id="req-1",
            item_id="pb_release",
            item_kind="playbook_run",
            summary="run it",
            requester="ana",
            approver="boss",
            created_at=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
            expires_after=timedelta(hours=24),
            escalation_chain=["boss", "auto"],
        )
    )
    return queue


class TestApprovalsSerde:
    def test_roundtrip_preserves_queue(self):
        queue = build_queue()
        assert ApprovalQueue.from_dict(queue.to_dict()) == queue

    def test_approvers_sorted_in_payload(self):
        names = [a["name"] for a in build_queue().to_dict()["approvers"]]
        assert names == ["auto", "boss"]

    def test_request_fields_survive(self):
        rebuilt = ApprovalQueue.from_dict(build_queue().to_dict())
        request = rebuilt.requests[0]
        assert request.status == ApprovalStatus.PENDING
        assert request.created_at == datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        assert request.expires_after == timedelta(hours=24)
        assert request.escalation_chain == ["boss", "auto"]

    def test_decided_state_survives(self):
        queue = build_queue()
        queue.decide("req-1", True, datetime(2026, 3, 2, 10, 0, tzinfo=UTC), note="ok")
        rebuilt = ApprovalQueue.from_dict(queue.to_dict())
        request = rebuilt.requests[0]
        assert request.status == ApprovalStatus.APPROVED
        assert request.decided_at == datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
        assert request.decision_note == "ok"

    def test_reloaded_queue_still_ticks_and_decides(self):
        queue = build_queue()
        rebuilt = ApprovalQueue.from_dict(queue.to_dict())
        expired = rebuilt.tick_expirations(datetime(2026, 3, 4, 9, 0, tzinfo=UTC))
        assert [r.request_id for r in expired] == ["req-1"]
        rebuilt2 = ApprovalQueue.from_dict(queue.to_dict())
        assert rebuilt2.decide("req-1", False, datetime(2026, 3, 2, 11, 0, tzinfo=UTC))

    def test_save_load_file(self, tmp_path):
        path = tmp_path / "queue.json"
        queue = build_queue()
        queue.save(path)
        assert ApprovalQueue.load(path) == queue

    def test_load_rejects_foreign_schema(self, tmp_path):
        from mnemofold.persist import write_envelope

        path = tmp_path / "bad.json"
        write_envelope(path, "bm25_index", {"docs": {}})
        with pytest.raises(PersistError, match="schema mismatch"):
            ApprovalQueue.load(path)
