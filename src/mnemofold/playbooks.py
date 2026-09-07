"""Playbooks: learned procedures from recurring workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from mnemofold.approvals import ApprovalQueue, ApprovalRequest, ApprovalStatus
from mnemofold.canon import sha256_hex
from mnemofold.persist import read_envelope, write_envelope
from mnemofold.tools import ToolPolicyError, ToolRegistry, ToolValidationError

PLAYBOOK_LIBRARY_SCHEMA = "playbook_library"
PLAYBOOK_LIBRARY_VERSION = 1


class PlaybookStatus(StrEnum):
    PROPOSED = "proposed"
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"


@dataclass(slots=True)
class PlaybookStep:
    step_id: str
    title: str
    description: str = ""
    tool: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    timeout_seconds: int = 300


@dataclass(slots=True)
class Playbook:
    playbook_id: str
    name: str
    description: str = ""
    status: PlaybookStatus = PlaybookStatus.PROPOSED
    version: int = 1
    steps: list[PlaybookStep] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    confidence: float = 0.0
    run_count: int = 0
    previous_versions: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = PlaybookStatus(self.status)
        if isinstance(self.tags, list):
            self.tags = set(self.tags)
        if not self.playbook_id:
            raise ValueError("playbook_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def total_steps(self) -> int:
        return len(self.steps)

    def can_run(self) -> bool:
        return self.status in {PlaybookStatus.APPROVED, PlaybookStatus.ACTIVE}

    def validate(self) -> list[str]:
        """Structural validation of steps and their preconditions.

        Checks:
        * all step ids are non-empty and unique
        * every precondition references a step that exists
        * no dependency cycles (via DFS)

        Returns a list of error strings; empty means valid.
        """
        errors: list[str] = []
        step_ids: list[str] = [s.step_id for s in self.steps]

        for i, sid in enumerate(step_ids):
            if not sid:
                errors.append(f"step {i}: empty step_id")

        if len(step_ids) != len(set(step_ids)):
            seen: set[str] = set()
            for sid in step_ids:
                if sid in seen:
                    errors.append(f"duplicate step_id: {sid!r}")
                seen.add(sid)

        id_set = set(step_ids)
        for step in self.steps:
            for pre in step.preconditions:
                if pre not in id_set:
                    errors.append(
                        f"step {step.step_id!r}: precondition references unknown step {pre!r}"
                    )

        # Cycle detection via DFS
        adj: dict[str, list[str]] = {s.step_id: list(s.preconditions) for s in self.steps}
        white, gray, black = 0, 1, 2
        color: dict[str, int] = {s.step_id: white for s in self.steps}

        def dfs(node: str) -> bool:
            color[node] = gray
            for nxt in adj.get(node, []):
                if nxt not in color:
                    continue
                if color[nxt] == gray:
                    return True
                if color[nxt] == white and dfs(nxt):
                    return True
            color[node] = black
            return False

        for sid in step_ids:
            if color[sid] == white and dfs(sid):
                errors.append(f"dependency cycle involving step {sid!r}")
                break

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Deterministic dict form; tags sorted, confidence quantized."""
        return {
            "playbook_id": self.playbook_id,
            "name": self.name,
            "description": self.description,
            "status": str(self.status),
            "version": self.version,
            "steps": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "description": s.description,
                    "tool": s.tool,
                    "inputs": dict(s.inputs),
                    "preconditions": list(s.preconditions),
                    "timeout_seconds": s.timeout_seconds,
                }
                for s in self.steps
            ],
            "tags": sorted(self.tags),
            "confidence": round(self.confidence, 6),
            "run_count": self.run_count,
            "previous_versions": list(self.previous_versions),
            "derived_from": list(self.derived_from),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Playbook:
        """Rebuild a playbook exactly as :meth:`to_dict` wrote it."""
        steps = [
            PlaybookStep(
                step_id=sd["step_id"],
                title=sd["title"],
                description=sd.get("description", ""),
                tool=sd.get("tool", ""),
                inputs=dict(sd.get("inputs", {})),
                preconditions=list(sd.get("preconditions", [])),
                timeout_seconds=sd.get("timeout_seconds", 300),
            )
            for sd in data.get("steps", [])
        ]
        return cls(
            playbook_id=data["playbook_id"],
            name=data["name"],
            description=data.get("description", ""),
            status=PlaybookStatus(data.get("status", PlaybookStatus.PROPOSED)),
            version=data.get("version", 1),
            steps=steps,
            tags=set(data.get("tags", [])),
            confidence=data.get("confidence", 0.0),
            run_count=data.get("run_count", 0),
            previous_versions=list(data.get("previous_versions", [])),
            derived_from=list(data.get("derived_from", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def digest(self) -> str:
        """SHA-256 over the canonical JSON form (stable across runs)."""
        return sha256_hex(self.to_dict())


@dataclass
class PlaybookLibrary:
    _playbooks: dict[str, Playbook] = field(default_factory=dict)

    def add(self, pb: Playbook) -> None:
        self._playbooks[pb.playbook_id] = pb

    def get(self, pid: str) -> Playbook | None:
        return self._playbooks.get(pid)

    def suggest(self, context_tags: set[str], top_k: int = 5) -> list[Playbook]:
        scored: list[tuple[Playbook, float]] = []
        for pb in self._playbooks.values():
            if pb.status in {PlaybookStatus.DEPRECATED, PlaybookStatus.REVOKED}:
                continue
            overlap = len(pb.tags & context_tags)
            score = overlap * pb.confidence
            if score > 0:
                scored.append((pb, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [pb for pb, _ in scored[:top_k]]

    def approve(self, pid: str, approver: str, timestamp: str) -> bool:
        pb = self._playbooks.get(pid)
        if pb is None or pb.status not in {PlaybookStatus.PROPOSED, PlaybookStatus.DRAFT}:
            return False
        pb.status = PlaybookStatus.APPROVED
        pb.metadata["approved_by"] = approver
        pb.metadata["approved_at"] = timestamp
        return True

    def deprecate(self, pid: str, reason: str) -> bool:
        pb = self._playbooks.get(pid)
        if pb is None or pb.status in {PlaybookStatus.DEPRECATED, PlaybookStatus.REVOKED}:
            return False
        pb.status = PlaybookStatus.DEPRECATED
        pb.metadata["deprecation_reason"] = reason
        return True

    def activate(self, pid: str) -> bool:
        """APPROVED -> ACTIVE. Only approved playbooks can go live."""
        pb = self._playbooks.get(pid)
        if pb is None or pb.status != PlaybookStatus.APPROVED:
            return False
        pb.status = PlaybookStatus.ACTIVE
        return True

    def revoke(self, pid: str, reason: str) -> bool:
        """Retire a playbook permanently.

        Revoked playbooks never run again and never surface in
        suggestions; revocation is one-way (unlike deprecation, which
        only closes the suggestion ranking, revocation marks the
        procedure as unsafe or obsolete).
        """
        pb = self._playbooks.get(pid)
        if pb is None or pb.status == PlaybookStatus.REVOKED:
            return False
        pb.status = PlaybookStatus.REVOKED
        pb.metadata["revocation_reason"] = reason
        return True

    def record_run(self, pid: str) -> bool:
        """Count one execution; only runnable playbooks may be recorded."""
        pb = self._playbooks.get(pid)
        if pb is None or not pb.can_run():
            return False
        pb.run_count += 1
        return True

    def create_revision(self, pid: str, new_steps: list[PlaybookStep]) -> Playbook | None:
        old = self._playbooks.get(pid)
        if old is None:
            return None
        new_id = f"{pid}_v{old.version + 1}"
        new_pb = Playbook(
            playbook_id=new_id,
            name=old.name,
            description=old.description,
            status=PlaybookStatus.DRAFT,
            version=old.version + 1,
            steps=list(new_steps),
            tags=set(old.tags),
            confidence=old.confidence * 0.9,
            previous_versions=old.previous_versions + [pid],
            derived_from=[pid],
        )
        self.add(new_pb)
        return new_pb

    def by_status(self, status: PlaybookStatus | str) -> list[Playbook]:
        if isinstance(status, str):
            status = PlaybookStatus(status)
        return [pb for pb in self._playbooks.values() if pb.status == status]

    def diff_versions(self, pid_a: str, pid_b: str) -> dict[str, Any]:
        """Compute a step-level diff between two playbook versions.

        Returns added/removed/modified step ids plus per-change details
        (title, tool, precondition count). The comparison is symmetric:
        swapping ``a`` and ``b`` swaps added and removed. Metadata and
        status changes are listed separately so callers can tell a
        substantive procedure edit from a status-only bump.
        """
        a = self._playbooks.get(pid_a)
        b = self._playbooks.get(pid_b)
        if a is None or b is None:
            missing = [p for p in (pid_a, pid_b) if self._playbooks.get(p) is None]
            return {"error": "missing_playbooks", "missing": missing}

        steps_a = {s.step_id: s for s in a.steps}
        steps_b = {s.step_id: s for s in b.steps}
        added = sorted(set(steps_b) - set(steps_a))
        removed = sorted(set(steps_a) - set(steps_b))
        common = sorted(set(steps_a) & set(steps_b))
        modified: list[dict[str, Any]] = []
        for sid in common:
            sa, sb = steps_a[sid], steps_b[sid]
            changes: list[str] = []
            if sa.title != sb.title:
                changes.append("title")
            if sa.tool != sb.tool:
                changes.append("tool")
            if sa.description != sb.description:
                changes.append("description")
            if sa.timeout_seconds != sb.timeout_seconds:
                changes.append("timeout")
            if set(sa.preconditions) != set(sb.preconditions):
                changes.append("preconditions")
            if sa.inputs != sb.inputs:
                changes.append("inputs")
            if changes:
                modified.append({"step_id": sid, "changes": changes})

        meta_changes: list[str] = []
        if a.status != b.status:
            meta_changes.append("status")
        if a.name != b.name:
            meta_changes.append("name")
        if a.description != b.description:
            meta_changes.append("description")
        if a.version != b.version:
            meta_changes.append("version")
        if a.confidence != b.confidence:
            meta_changes.append("confidence")
        if set(a.tags) != set(b.tags):
            meta_changes.append("tags")

        return {
            "a": pid_a,
            "b": pid_b,
            "steps_added": added,
            "steps_removed": removed,
            "steps_modified": modified,
            "meta_changes": sorted(meta_changes),
        }

    def export_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """Return all playbooks carrying ``tag`` as deterministic dicts.

        Results are sorted by playbook id so the same library always
        produces the same export order. Useful for serializing subsets
        of the library (e.g. all "release" playbooks) without dumping
        the whole thing.
        """
        matches = [pb for pb in self._playbooks.values() if tag in pb.tags]
        return [pb.to_dict() for pb in sorted(matches, key=lambda p: p.playbook_id)]

    def total_count(self) -> int:
        return len(self._playbooks)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic dict: playbooks sorted by id, statuses as strings."""
        return {"playbooks": [self._playbooks[pid].to_dict() for pid in sorted(self._playbooks)]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlaybookLibrary:
        """Rebuild a library from :meth:`to_dict` output."""
        library = cls()
        for payload in data.get("playbooks", []):
            library.add(Playbook.from_dict(payload))
        return library

    def save(self, path: str | Path) -> None:
        """Write the library to ``path`` as a versioned envelope."""
        write_envelope(
            path, PLAYBOOK_LIBRARY_SCHEMA, self.to_dict(), version=PLAYBOOK_LIBRARY_VERSION
        )

    @classmethod
    def load(cls, path: str | Path) -> PlaybookLibrary:
        """Load a library written by :meth:`save`."""
        return cls.from_dict(
            read_envelope(path, PLAYBOOK_LIBRARY_SCHEMA, version=PLAYBOOK_LIBRARY_VERSION)
        )


@dataclass(slots=True)
class PlaybookStepResult:
    """Outcome of executing one playbook step."""

    step_id: str
    tool: str
    success: bool
    output: Any = None
    error: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "skipped": self.skipped,
        }


@dataclass(slots=True)
class PlaybookRunReport:
    """What one gated playbook execution did.

    ``status`` is one of ``completed`` (every step ran), ``failed`` (a
    step errored and execution stopped there), ``not_approved`` (the
    request was denied, expired or is still pending), ``blocked`` (the
    playbook cannot run or is structurally invalid) and
    ``unknown_request``.
    """

    playbook_id: str
    request_id: str
    status: str
    step_results: list[PlaybookStepResult] = field(default_factory=list)
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "request_id": self.request_id,
            "status": self.status,
            "error": self.error,
            "step_results": [r.to_dict() for r in self.step_results],
        }


def _order_playbook_steps(pb: Playbook) -> list[PlaybookStep]:
    """Deterministic precondition order over the declared steps.

    Repeatedly takes the first declared step whose preconditions are
    all ordered already. ``Playbook.validate`` rejects cycles before
    execution, but the ordering never hangs even if one slips through:
    whatever remains is appended in declaration order.
    """
    remaining = list(pb.steps)
    ordered: list[PlaybookStep] = []
    done: set[str] = set()
    while remaining:
        for i, step in enumerate(remaining):
            if all(p in done for p in step.preconditions):
                ordered.append(step)
                done.add(step.step_id)
                remaining.pop(i)
                break
        else:
            ordered.extend(remaining)
            break
    return ordered


@dataclass
class PlaybookRunner:
    """Execute playbooks strictly behind approval gates.

    Lifecycle (no wall-clock reads; callers pass every timestamp):

    1. :meth:`request_run` submits an ``ApprovalRequest`` for a
       playbook that may run (APPROVED/ACTIVE). Proposed, draft,
       deprecated and revoked playbooks cannot be requested.
    2. The approval queue resolves the request — personas, manual
       ``decide`` calls or expiry. The runner never bypasses it.
    3. :meth:`execute` runs each step's tool through the registry in
       precondition order when (and only when) the request shows
       APPROVED. The first failing step stops the run; ``run_count``
       only grows for completed runs.
    """

    library: PlaybookLibrary
    queue: ApprovalQueue
    registry: ToolRegistry

    def request_run(
        self,
        pid: str,
        *,
        requester: str,
        approver: str,
        now: datetime,
        expires_after: timedelta | None = None,
    ) -> str | None:
        """Submit an approval request to run playbook ``pid``.

        Returns the request id, or None when the playbook is unknown or
        not in a runnable status.
        """
        pb = self.library.get(pid)
        if pb is None or not pb.can_run():
            return None
        request_id = f"pbrun_{pid}_{len(self.queue.requests) + 1}"
        self.queue.submit(
            ApprovalRequest(
                request_id=request_id,
                item_id=pid,
                item_kind="playbook_run",
                summary=f"run playbook {pb.name!r} v{pb.version}",
                requester=requester,
                approver=approver,
                created_at=now,
                expires_after=expires_after,
            )
        )
        return request_id

    def execute(self, request_id: str) -> PlaybookRunReport:
        """Run the playbook attached to an approved request."""
        request = next((r for r in self.queue.requests if r.request_id == request_id), None)
        if request is None:
            return PlaybookRunReport(
                playbook_id="", request_id=request_id, status="unknown_request"
            )
        pid = request.item_id
        if request.status != ApprovalStatus.APPROVED:
            return PlaybookRunReport(
                playbook_id=pid,
                request_id=request_id,
                status="not_approved",
                error=str(request.status),
            )
        pb = self.library.get(pid)
        if pb is None or not pb.can_run():
            return PlaybookRunReport(playbook_id=pid, request_id=request_id, status="blocked")
        validation = pb.validate()
        if validation:
            return PlaybookRunReport(
                playbook_id=pid,
                request_id=request_id,
                status="blocked",
                error="; ".join(validation),
            )
        results: list[PlaybookStepResult] = []
        for step in _order_playbook_steps(pb):
            if not step.tool:
                results.append(
                    PlaybookStepResult(step_id=step.step_id, tool="", success=True, skipped=True)
                )
                continue
            try:
                outcome = self.registry.invoke(step.tool, dict(step.inputs))
            except (ToolValidationError, ToolPolicyError) as exc:
                results.append(
                    PlaybookStepResult(
                        step_id=step.step_id, tool=step.tool, success=False, error=str(exc)
                    )
                )
                return PlaybookRunReport(
                    playbook_id=pid,
                    request_id=request_id,
                    status="failed",
                    step_results=results,
                )
            results.append(
                PlaybookStepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    success=outcome.success,
                    output=outcome.output,
                    error=outcome.error,
                )
            )
            if not outcome.success:
                return PlaybookRunReport(
                    playbook_id=pid,
                    request_id=request_id,
                    status="failed",
                    step_results=results,
                )
        self.library.record_run(pid)
        return PlaybookRunReport(
            playbook_id=pid, request_id=request_id, status="completed", step_results=results
        )
