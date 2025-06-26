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

    def total_count(self) -> int:
        return len(self._playbooks)
