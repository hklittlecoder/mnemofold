from datetime import UTC, datetime, timedelta

from mnemofold.approvals import (
    ApprovalQueue,
    ApprovalRequest,
    ApprovalStatus,
    Approver,
    ApproverPersona,
)

TZ = UTC
NOW = datetime(2026, 3, 15, 10, 0, 0, tzinfo=TZ)


def _make_request(**overrides):
    base = dict(
        request_id="r1",
        item_id="tool:send_email",
        item_kind="tool_use",
        summary="Send weekly digest",
        requester="assistant",
        approver="alice",
        created_at=NOW,
    )
    base.update(overrides)
    return ApprovalRequest(**base)


def test_approval_request_defaults():
    r = _make_request()
    assert r.status == ApprovalStatus.PENDING
    assert r.is_open() is True
    assert r.escalated_from is None
    assert r.escalation_chain == []


def test_submit_and_pending():
    q = ApprovalQueue()
    q.submit(_make_request(request_id="r1"))
    q.submit(_make_request(request_id="r2", approver="bob"))
    assert len(q.pending()) == 2


def test_decide_approved():
    q = ApprovalQueue()
    q.submit(_make_request())
    r = q.decide("r1", True, NOW + timedelta(hours=1), note="looks good")
    assert r is not None
    assert r.status == ApprovalStatus.APPROVED
    assert r.decided_at == NOW + timedelta(hours=1)
    assert r.decision_note == "looks good"
    assert len(q.pending()) == 0


def test_decide_denied():
    q = ApprovalQueue()
    q.submit(_make_request())
    r = q.decide("r1", False, NOW, note="not yet")
    assert r.status == ApprovalStatus.DENIED


def test_decide_unknown_request():
    q = ApprovalQueue()
    assert q.decide("nope", True, NOW) is None


def test_expiration():
    q = ApprovalQueue()
    q.submit(
        _make_request(
            request_id="r1",
            expires_after=timedelta(hours=1),
        )
    )
    q.submit(
        _make_request(
            request_id="r2",
            expires_after=timedelta(days=1),
        )
    )
    expired = q.tick_expirations(NOW + timedelta(hours=2))
    assert len(expired) == 1
    assert expired[0].request_id == "r1"
    assert expired[0].status == ApprovalStatus.EXPIRED
    assert len(q.pending()) == 1


def test_expiration_without_deadline():
    q = ApprovalQueue()
    q.submit(_make_request(request_id="r1", expires_after=None))
    expired = q.tick_expirations(NOW + timedelta(days=365))
    assert expired == []


def test_escalation():
    q = ApprovalQueue()
    q.submit(
        _make_request(
            request_id="r1",
            approver="alice",
            escalation_chain=["alice", "bob", "carol"],
        )
    )
    r = q.escalate("r1", NOW + timedelta(hours=1))
    assert r is not None
    assert r.approver == "bob"
    assert r.escalated_from == "alice"
    assert r.is_open() is True


def test_escalation_end_of_chain():
    q = ApprovalQueue()
    q.submit(
        _make_request(
            request_id="r1",
            approver="carol",
            escalation_chain=["alice", "bob", "carol"],
        )
    )
    r = q.escalate("r1", NOW)
    assert r is None


def test_auto_resolve_auto_approve():
    q = ApprovalQueue()
    q.add_approver(
        Approver(name="alice", persona=ApproverPersona.AUTO_APPROVE, decision_latency=timedelta())
    )
    q.submit(_make_request(request_id="r1", approver="alice"))
    resolved = q.auto_resolve(NOW + timedelta(seconds=1))
    assert len(resolved) == 1
    assert resolved[0].status == ApprovalStatus.APPROVED
    assert "auto-approved" in resolved[0].decision_note


def test_auto_resolve_auto_deny():
    q = ApprovalQueue()
    q.add_approver(
        Approver(name="bob", persona=ApproverPersona.AUTO_DENY, decision_latency=timedelta())
    )
    q.submit(_make_request(request_id="r1", approver="bob"))
    resolved = q.auto_resolve(NOW + timedelta(seconds=1))
    assert len(resolved) == 1
    assert resolved[0].status == ApprovalStatus.DENIED


def test_auto_resolve_ask_waits():
    q = ApprovalQueue()
    q.add_approver(Approver(name="carol", persona=ApproverPersona.ASK))
    q.submit(_make_request(request_id="r1", approver="carol"))
    resolved = q.auto_resolve(NOW + timedelta(days=7))
    assert resolved == []
    assert len(q.pending()) == 1


def test_auto_resolve_respects_latency():
    q = ApprovalQueue()
    q.add_approver(
        Approver(
            name="dave", persona=ApproverPersona.AUTO_APPROVE, decision_latency=timedelta(hours=24)
        )
    )
    q.submit(_make_request(request_id="r1", approver="dave"))
    # Too early
    assert q.auto_resolve(NOW + timedelta(hours=1)) == []
    # Late enough
    resolved = q.auto_resolve(NOW + timedelta(hours=25))
    assert len(resolved) == 1


def test_audit_metrics():
    q = ApprovalQueue()
    q.submit(_make_request(request_id="r1", approver="a"))
    q.submit(_make_request(request_id="r2", approver="a"))
    q.decide("r1", True, NOW)
    metrics = q.audit_metrics()
    assert metrics["approved"] == 1
    assert metrics["pending"] == 1
