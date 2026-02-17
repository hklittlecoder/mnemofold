"""Golden bytes for the persisted approval queue.

The fixture is reconstructed from the public API — approvers, requests,
one manual decision — so any drift in field names, ISO formatting or
ordering fails here deliberately.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mnemofold.approvals import (
    ApprovalQueue,
    ApprovalRequest,
    Approver,
    ApproverPersona,
)

FIXTURE = Path(__file__).parent / "fixtures" / "approval_queue_golden.json"


def build_queue() -> ApprovalQueue:
    queue = ApprovalQueue()
    queue.add_approver(
        Approver(
            name="auto",
            persona=ApproverPersona.AUTO_APPROVE,
            decision_latency=timedelta(hours=1),
        )
    )
    queue.add_approver(
        Approver(
            name="boss",
            persona=ApproverPersona.ASK,
            escalation_to="auto",
            decision_latency=timedelta(hours=2),
        )
    )
    queue.submit(
        ApprovalRequest(
            request_id="req-1",
            item_id="pb_release",
            item_kind="playbook_run",
            summary="run playbook 'Release' v1",
            requester="ana",
            approver="boss",
            created_at=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
            expires_after=timedelta(hours=24),
            escalation_chain=["boss", "auto"],
        )
    )
    queue.decide("req-1", True, datetime(2026, 3, 2, 10, 30, tzinfo=UTC), note="ok")
    queue.submit(
        ApprovalRequest(
            request_id="req-2",
            item_id="pb_deploy",
            item_kind="playbook_run",
            summary="run playbook 'Deploy' v2",
            requester="bo",
            approver="auto",
            created_at=datetime(2026, 3, 3, 9, 0, tzinfo=UTC),
        )
    )
    return queue


def test_save_matches_golden_bytes(tmp_path):
    path = tmp_path / "queue.json"
    build_queue().save(path)
    assert path.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")


def test_golden_loads_to_equal_queue():
    assert ApprovalQueue.load(FIXTURE) == build_queue()


def test_regeneration_is_stable(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    build_queue().save(a)
    build_queue().save(b)
    assert a.read_bytes() == b.read_bytes() == FIXTURE.read_bytes()
