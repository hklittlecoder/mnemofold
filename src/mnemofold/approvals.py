"""Approval queue with personas and escalation chains.

The approval queue holds items that need human (or scripted-persona)
sign-off before execution.  Approver personas (auto-approve, ask, deny)
drive tests offline.  Escalation chains forward items when the primary
approver times out, and audit metrics track decisions in simulated time.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from mnemofold.persist import read_envelope, write_envelope

APPROVAL_QUEUE_SCHEMA = "approval_queue"
APPROVAL_QUEUE_VERSION = 1


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    ESCALATED = "escalated"
    EXPIRED = "expired"


class ApproverPersona(StrEnum):
    """Scripted approver behavior for tests and simulations."""

    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    ASK = "ask"
    RANDOM = "random"


@dataclass(slots=True)
class ApprovalRequest:
    """A single pending approval."""

    request_id: str
    item_id: str
    item_kind: str
    summary: str
    requester: str
    approver: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime | None = None
    decided_at: datetime | None = None
    decision_note: str = ""
    escalated_from: str | None = None
    escalation_chain: list[str] = field(default_factory=list)
    escalation_count: int = 0
    expires_after: timedelta | None = None

    def is_open(self) -> bool:
        return self.status == ApprovalStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        """Serializable form; instants as ISO strings, expiry as seconds."""
        return {
            "request_id": self.request_id,
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "summary": self.summary,
            "requester": self.requester,
            "approver": self.approver,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_note": self.decision_note,
            "escalated_from": self.escalated_from,
            "escalation_chain": list(self.escalation_chain),
            "escalation_count": self.escalation_count,
            "expires_after_seconds": (
                self.expires_after.total_seconds() if self.expires_after is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        """Rebuild a request from :meth:`to_dict` output."""
        created = data.get("created_at")
        decided = data.get("decided_at")
        expiry = data.get("expires_after_seconds")
        return cls(
            request_id=data["request_id"],
            item_id=data["item_id"],
            item_kind=data["item_kind"],
            summary=data.get("summary", ""),
            requester=data.get("requester", ""),
            approver=data.get("approver", ""),
            status=ApprovalStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(created) if created else None,
            decided_at=datetime.fromisoformat(decided) if decided else None,
            decision_note=data.get("decision_note", ""),
            escalated_from=data.get("escalated_from"),
            escalation_chain=list(data.get("escalation_chain", [])),
            escalation_count=int(data.get("escalation_count", 0)),
            expires_after=timedelta(seconds=float(expiry)) if expiry is not None else None,
        )


@dataclass
class Approver:
    """An approver identity with a persona and escalation target."""

    name: str
    persona: ApproverPersona = ApproverPersona.ASK
    escalation_to: str | None = None
    decision_latency: timedelta = timedelta(hours=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "persona": self.persona.value,
            "escalation_to": self.escalation_to,
            "decision_latency_seconds": self.decision_latency.total_seconds(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Approver:
        return cls(
            name=data["name"],
            persona=ApproverPersona(data.get("persona", "ask")),
            escalation_to=data.get("escalation_to"),
            decision_latency=timedelta(seconds=float(data.get("decision_latency_seconds", 7200.0))),
        )


@dataclass(slots=True)
class TickReport:
    """What one :meth:`ApprovalQueue.tick` changed."""

    expired: list[ApprovalRequest] = field(default_factory=list)
    resolved: list[ApprovalRequest] = field(default_factory=list)
    escalated: list[ApprovalRequest] = field(default_factory=list)

    def total_touched(self) -> int:
        return len(self.expired) + len(self.resolved) + len(self.escalated)


@dataclass
class ApprovalQueue:
    """Queue of pending approvals with persona-driven resolution."""

    approvers: dict[str, Approver] = field(default_factory=dict)
    requests: list[ApprovalRequest] = field(default_factory=list)

    def add_approver(self, approver: Approver) -> None:
        self.approvers[approver.name] = approver

    def submit(self, request: ApprovalRequest) -> None:
        self.requests.append(request)

    def pending(self) -> list[ApprovalRequest]:
        return [r for r in self.requests if r.is_open()]

    def decide(
        self,
        request_id: str,
        approved: bool,
        now: datetime,
        note: str = "",
    ) -> ApprovalRequest | None:
        for r in self.requests:
            if r.request_id == request_id and r.is_open():
                r.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
                r.decided_at = now
                r.decision_note = note
                return r
        return None

    def tick_expirations(self, now: datetime) -> list[ApprovalRequest]:
        """Expire requests past their deadline; return expired list."""
        expired: list[ApprovalRequest] = []
        for r in self.requests:
            if not r.is_open() or r.expires_after is None or r.created_at is None:
                continue
            if now >= r.created_at + r.expires_after:
                r.status = ApprovalStatus.EXPIRED
                r.decided_at = now
                expired.append(r)
        return expired

    def escalate(self, request_id: str, now: datetime) -> ApprovalRequest | None:
        """Move a pending request to the next approver in its chain."""
        for r in self.requests:
            if r.request_id != request_id or not r.is_open():
                continue
            chain = r.escalation_chain
            if not chain:
                return None
            idx = chain.index(r.approver) if r.approver in chain else -1
            if idx < 0 or idx + 1 >= len(chain):
                return None
            r.escalated_from = r.approver
            r.approver = chain[idx + 1]
            r.escalation_count += 1
            # The request stays PENDING under the new approver; the audit
            # trail lives in escalated_from/escalation_count, so metrics
            # can count escalations without a transient status flip that
            # used to overwrite itself before anything could observe it.
            r.created_at = now
            return r
        return None

    def auto_resolve(
        self,
        now: datetime,
        rng_seed: int | None = None,
    ) -> list[ApprovalRequest]:
        """Let scripted personas resolve pending requests that are due.

        AUTO_APPROVE always approves; AUTO_DENY always denies; ASK never
        auto-resolves; RANDOM flips a coin using an RNG seeded from
        ``rng_seed`` combined with a stable digest of the request id
        (the built-in hash is salted per process, which made decisions
        differ between runs).
        """
        resolved: list[ApprovalRequest] = []
        for r in list(self.pending()):
            approver = self.approvers.get(r.approver)
            if approver is None:
                continue
            if r.created_at and now < r.created_at + approver.decision_latency:
                continue
            persona = approver.persona
            if persona == ApproverPersona.AUTO_APPROVE:
                self.decide(r.request_id, True, now, note="auto-approved")
            elif persona == ApproverPersona.AUTO_DENY:
                self.decide(r.request_id, False, now, note="auto-denied")
            elif persona == ApproverPersona.RANDOM:
                digest = hashlib.sha256(r.request_id.encode("utf-8")).hexdigest()
                seed = (rng_seed or 0) + int(digest[:8], 16)
                persona_rng = random.Random(seed)
                self.decide(r.request_id, persona_rng.random() < 0.5, now, note="random")
            else:
                continue
            resolved.append(r)
        return resolved

    def due_for_escalation(self, now: datetime) -> list[ApprovalRequest]:
        """Pending requests whose approver is past latency and has a successor.

        A request is due for escalation when it is still open, its current
        approver's ``decision_latency`` has elapsed since ``created_at``,
        and the escalation chain has a next approver after the current one.
        Returned in submission order for determinism.
        """
        due: list[ApprovalRequest] = []
        for r in self.requests:
            if not r.is_open() or r.created_at is None:
                continue
            approver = self.approvers.get(r.approver)
            if approver is None:
                continue
            if now < r.created_at + approver.decision_latency:
                continue
            chain = r.escalation_chain
            if r.approver in chain and chain.index(r.approver) + 1 < len(chain):
                due.append(r)
        return due

    def tick(self, now: datetime, rng_seed: int | None = None) -> TickReport:
        """Advance simulated time by one step, in a fixed order.

        Order (deterministic, so a replayed timeline matches byte-for-byte):
        1. expire overdue requests;
        2. let scripted personas resolve requests that are due;
        3. escalate still-pending requests whose approver timed out.

        Escalation runs last so a request the personas just resolved is
        not also escalated in the same tick.
        """
        expired = self.tick_expirations(now)
        resolved = self.auto_resolve(now, rng_seed=rng_seed)
        escalated: list[ApprovalRequest] = []
        for r in self.due_for_escalation(now):
            moved = self.escalate(r.request_id, now)
            if moved is not None:
                escalated.append(moved)
        return TickReport(expired=expired, resolved=resolved, escalated=escalated)

    def bulk_decide(
        self,
        request_ids: list[str],
        approved: bool,
        now: datetime,
        note: str = "",
    ) -> list[ApprovalRequest]:
        """Decide multiple requests at once; return successfully decided ones.

        Only currently-pending requests are affected; ids that are not
        found or already decided are silently skipped (callers that need
        per-id resolution can compare the returned list length).
        Decisions are applied in request-id order for determinism.
        """
        decided: list[ApprovalRequest] = []
        for rid in sorted(request_ids):
            result = self.decide(rid, approved, now, note=note)
            if result is not None:
                decided.append(result)
        return decided

    def audit_metrics(self) -> dict[str, int]:
        """Count of requests by status plus total escalations, for dashboards."""
        counts: dict[str, int] = {}
        for r in self.requests:
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        counts["escalations"] = sum(r.escalation_count for r in self.requests)
        return counts

    def to_dict(self) -> dict[str, Any]:
        """Deterministic form: approvers sorted by name, requests in order.

        Request order is submission order — escalation and expiry logic
        both walk the list, so :meth:`from_dict` replays it exactly.
        """
        return {
            "approvers": [self.approvers[name].to_dict() for name in sorted(self.approvers)],
            "requests": [request.to_dict() for request in self.requests],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalQueue:
        """Rebuild a queue from :meth:`to_dict` output."""
        queue = cls()
        for approver in data.get("approvers", []):
            queue.add_approver(Approver.from_dict(approver))
        for request in data.get("requests", []):
            queue.submit(ApprovalRequest.from_dict(request))
        return queue

    def save(self, path: str | Path) -> None:
        """Write the queue to ``path`` as a versioned envelope."""
        write_envelope(path, APPROVAL_QUEUE_SCHEMA, self.to_dict(), version=APPROVAL_QUEUE_VERSION)

    @classmethod
    def load(cls, path: str | Path) -> ApprovalQueue:
        """Load a queue written by :meth:`save`."""
        data = read_envelope(path, APPROVAL_QUEUE_SCHEMA, version=APPROVAL_QUEUE_VERSION)
        return cls.from_dict(data)

    def stats_by_approver(self) -> dict[str, dict[str, int]]:
        """Per-approver outcome counts for audit dashboards.

        Covers every request currently or previously assigned to each
        registered approver, broken down by status, plus an
        ``escalated_away`` counter for requests an approver let escalate.
        Requests naming an unregistered approver still appear, so the
        breakdown never silently drops history. Keys are sorted for
        deterministic reports.
        """
        stats: dict[str, dict[str, int]] = {name: {} for name in sorted(self.approvers)}
        for request in self.requests:
            bucket = stats.setdefault(request.approver, {})
            key = request.status.value
            bucket[key] = bucket.get(key, 0) + 1
            if request.escalated_from:
                source = stats.setdefault(request.escalated_from, {})
                source["escalated_away"] = source.get("escalated_away", 0) + 1
        return {name: dict(sorted(stats[name].items())) for name in sorted(stats)}
