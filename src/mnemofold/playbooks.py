"""Playbooks: learned procedures from recurring workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
