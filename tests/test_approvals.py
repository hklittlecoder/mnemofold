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


def _ask_queue() -> ApprovalQueue:
    q = ApprovalQueue()
    q.add_approver(Approver(name="alice", persona=ApproverPersona.ASK))
    q.add_approver(Approver(name="bob", persona=ApproverPersona.ASK))
    q.submit(
        ApprovalRequest(
            request_id="r1",
            item_id="i1",
            item_kind="tool",
            summary="deploy",
            requester="carol",
            approver="alice",
            escalation_chain=["alice", "bob"],
            created_at=NOW,
        )
    )
    return q


class TestEscalationAuditTrail:
    def test_escalation_count_increments_and_status_stays_pending(self):
        q = _ask_queue()
        r = q.escalate("r1", NOW + timedelta(hours=3))
        assert r is not None
        assert r.escalation_count == 1
        assert r.approver == "bob"
        assert r.escalated_from == "alice"
        assert r.status == ApprovalStatus.PENDING
        assert r.is_open()

    def test_repeated_escalations_accumulate(self):
        q = _ask_queue()
        q.requests[0].escalation_chain = ["alice", "bob", "carol"]
        q.add_approver(Approver(name="carol", persona=ApproverPersona.ASK))
        q.escalate("r1", NOW + timedelta(hours=1))
        r = q.escalate("r1", NOW + timedelta(hours=2))
        assert r is not None
        assert r.escalation_count == 2
        assert r.approver == "carol"

    def test_audit_metrics_reports_escalations(self):
        q = _ask_queue()
        q.escalate("r1", NOW + timedelta(hours=3))
        metrics = q.audit_metrics()
        assert metrics["pending"] == 1
        assert metrics["escalations"] == 1
        assert "escalated" not in metrics  # no transient status anymore


class TestRandomPersonaDeterminism:
    def _queue(self) -> ApprovalQueue:
        q = ApprovalQueue()
        q.add_approver(
            Approver(
                name="rand",
                persona=ApproverPersona.RANDOM,
                decision_latency=timedelta(),
            )
        )
        for i in range(10):
            q.submit(
                ApprovalRequest(
                    request_id=f"r{i}",
                    item_id=f"i{i}",
                    item_kind="tool",
                    summary="s",
                    requester="x",
                    approver="rand",
                    created_at=NOW,
                )
            )
        return q

    def test_same_seed_same_decisions(self):
        first = self._queue()
        first.auto_resolve(NOW + timedelta(seconds=1), rng_seed=42)
        second = self._queue()
        second.auto_resolve(NOW + timedelta(seconds=1), rng_seed=42)
        decisions_a = [(r.request_id, r.status) for r in first.requests]
        decisions_b = [(r.request_id, r.status) for r in second.requests]
        assert decisions_a == decisions_b

    def test_decisions_are_decided_not_pending(self):
        q = self._queue()
        q.auto_resolve(NOW + timedelta(seconds=1), rng_seed=7)
        assert q.pending() == []
        assert all(r.status in (ApprovalStatus.APPROVED, ApprovalStatus.DENIED) for r in q.requests)


class TestApprovalTick:
    def _queue_with_ask_chain(self) -> ApprovalQueue:
        q = ApprovalQueue()
        q.add_approver(
            Approver(name="alice", persona=ApproverPersona.ASK, decision_latency=timedelta(hours=1))
        )
        q.add_approver(Approver(name="bob", persona=ApproverPersona.ASK))
        q.submit(
            ApprovalRequest(
                request_id="r1",
                item_id="i1",
                item_kind="tool",
                summary="deploy",
                requester="carol",
                approver="alice",
                escalation_chain=["alice", "bob"],
                created_at=NOW,
            )
        )
        return q

    def test_tick_escalates_after_latency(self):
        q = self._queue_with_ask_chain()
        report = q.tick(NOW + timedelta(hours=2))
        assert [r.request_id for r in report.escalated] == ["r1"]
        assert q.requests[0].approver == "bob"
        assert report.expired == [] and report.resolved == []

    def test_tick_before_latency_does_nothing(self):
        q = self._queue_with_ask_chain()
        report = q.tick(NOW + timedelta(minutes=30))
        assert report.total_touched() == 0
        assert q.requests[0].approver == "alice"

    def test_tick_resolves_auto_approve_before_escalation(self):
        q = ApprovalQueue()
        q.add_approver(
            Approver(
                name="dave",
                persona=ApproverPersona.AUTO_APPROVE,
                decision_latency=timedelta(hours=1),
                escalation_to="erin",
            )
        )
        q.add_approver(Approver(name="erin", persona=ApproverPersona.ASK))
        q.submit(
            ApprovalRequest(
                request_id="r1",
                item_id="i1",
                item_kind="tool",
                summary="s",
                requester="x",
                approver="dave",
                escalation_chain=["dave", "erin"],
                created_at=NOW,
            )
        )
        report = q.tick(NOW + timedelta(hours=2))
        assert [r.request_id for r in report.resolved] == ["r1"]
        assert report.escalated == []  # resolved, so not escalated
        assert q.requests[0].status == ApprovalStatus.APPROVED

    def test_tick_expires_first(self):
        q = ApprovalQueue()
        q.add_approver(
            Approver(name="alice", persona=ApproverPersona.ASK, decision_latency=timedelta(hours=1))
        )
        q.submit(
            ApprovalRequest(
                request_id="r1",
                item_id="i1",
                item_kind="tool",
                summary="s",
                requester="x",
                approver="alice",
                escalation_chain=["alice", "bob"],
                created_at=NOW,
                expires_after=timedelta(minutes=30),
            )
        )
        report = q.tick(NOW + timedelta(hours=2))
        assert [r.request_id for r in report.expired] == ["r1"]
        assert report.escalated == []  # expired requests are not open
        assert q.requests[0].status == ApprovalStatus.EXPIRED

    def test_due_for_escalation_needs_successor(self):
        q = ApprovalQueue()
        q.add_approver(
            Approver(name="solo", persona=ApproverPersona.ASK, decision_latency=timedelta())
        )
        q.submit(
            ApprovalRequest(
                request_id="r1",
                item_id="i1",
                item_kind="tool",
                summary="s",
                requester="x",
                approver="solo",
                escalation_chain=["solo"],
                created_at=NOW,
            )
        )
        # solo is last in the chain -> nowhere to escalate
        assert q.due_for_escalation(NOW + timedelta(hours=1)) == []

    def test_tick_is_deterministic(self):
        first = self._queue_with_ask_chain().tick(NOW + timedelta(hours=2))
        second = self._queue_with_ask_chain().tick(NOW + timedelta(hours=2))
        assert [r.request_id for r in first.escalated] == [r.request_id for r in second.escalated]


class TestApprovalQueueEdges:
    def _request(self, rid: str, **kwargs) -> ApprovalRequest:
        base = {
            "request_id": rid,
            "item_id": f"i-{rid}",
            "item_kind": "tool",
            "summary": "s",
            "requester": "req",
            "approver": "app",
            "created_at": NOW,
        }
        base.update(kwargs)
        return ApprovalRequest(**base)

    def test_decide_unknown_request_returns_none(self):
        assert ApprovalQueue().decide("ghost", True, NOW) is None

    def test_decide_twice_second_is_noop(self):
        q = ApprovalQueue()
        q.submit(self._request("r1"))
        assert q.decide("r1", True, NOW) is not None
        assert q.decide("r1", False, NOW) is None  # already decided
        assert q.requests[0].status == ApprovalStatus.APPROVED

    def test_pending_excludes_decided(self):
        q = ApprovalQueue()
        q.submit(self._request("r1"))
        q.submit(self._request("r2"))
        q.decide("r1", True, NOW)
        assert [r.request_id for r in q.pending()] == ["r2"]

    def test_expire_boundary_is_inclusive(self):
        q = ApprovalQueue()
        q.submit(self._request("r1", expires_after=timedelta(hours=1)))
        # exactly at the deadline -> expired (>=)
        expired = q.tick_expirations(NOW + timedelta(hours=1))
        assert [r.request_id for r in expired] == ["r1"]

    def test_no_expiry_never_expires(self):
        q = ApprovalQueue()
        q.submit(self._request("r1"))
        assert q.tick_expirations(NOW + timedelta(days=365)) == []

    def test_escalation_without_chain_returns_none(self):
        q = ApprovalQueue()
        q.submit(self._request("r1"))
        assert q.escalate("r1", NOW) is None

    def test_auto_resolve_skips_unknown_approver(self):
        q = ApprovalQueue()
        q.submit(self._request("r1", approver="nobody"))
        assert q.auto_resolve(NOW + timedelta(hours=1)) == []

    def test_auto_deny_persona(self):
        q = ApprovalQueue()
        q.add_approver(
            Approver(name="app", persona=ApproverPersona.AUTO_DENY, decision_latency=timedelta())
        )
        q.submit(self._request("r1"))
        q.auto_resolve(NOW + timedelta(seconds=1))
        assert q.requests[0].status == ApprovalStatus.DENIED

    def test_ask_persona_never_auto_resolves(self):
        q = ApprovalQueue()
        q.add_approver(
            Approver(name="app", persona=ApproverPersona.ASK, decision_latency=timedelta())
        )
        q.submit(self._request("r1"))
        assert q.auto_resolve(NOW + timedelta(hours=100)) == []
        assert q.requests[0].status == ApprovalStatus.PENDING

    def test_audit_metrics_counts_every_status(self):
        q = ApprovalQueue()
        q.submit(self._request("a"))
        q.submit(self._request("b"))
        q.submit(self._request("c", expires_after=timedelta(seconds=1)))
        q.decide("a", True, NOW)
        q.decide("b", False, NOW)
        q.tick_expirations(NOW + timedelta(seconds=2))
        metrics = q.audit_metrics()
        assert metrics["approved"] == 1
        assert metrics["denied"] == 1
        assert metrics["expired"] == 1
        assert metrics["escalations"] == 0

    def test_decision_note_recorded(self):
        q = ApprovalQueue()
        q.submit(self._request("r1"))
        r = q.decide("r1", True, NOW, note="looks safe")
        assert r is not None
        assert r.decision_note == "looks safe"
        assert r.decided_at == NOW
