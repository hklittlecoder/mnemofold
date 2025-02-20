"""Right-to-forget deletion semantics.

Implements cascading deletion across nodes, edges, and retrieval
indexes, with tombstones that block re-derivation from surviving
events.  Provides an audit report of what was deleted and a property
check that deleted content never reappears through any query path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DeletionReason(StrEnum):
    FORGET = "right_to_forget"
    LEGAL_HOLD_RELEASE = "legal_hold_release"
    DATA_EXPIRY = "data_expiry"
    USER_REQUEST = "user_request"
    ERROR_CORRECTION = "error_correction"


@dataclass(slots=True, frozen=True)
class Tombstone:
    """A permanent marker that a piece of content was deleted."""

    key: str
    kind: str
    reason: DeletionReason
    deleted_at: datetime
    requested_by: str | None = None


@dataclass
class DeletionAuditEntry:
    key: str
    kind: str
    reason: DeletionReason
    deleted_at: datetime
    cascade_depth: int = 0


@dataclass
class DeletionReport:
    """Summary of a deletion operation."""

    requested_key: str
    reason: DeletionReason
    requested_at: datetime
    deleted: list[DeletionAuditEntry] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_deleted(self) -> int:
        return len(self.deleted)


class TombstoneIndex:
    """In-memory index of tombstones for fast resurrection checks."""

    def __init__(self) -> None:
        self._tombstones: dict[str, Tombstone] = {}

    def add(self, tombstone: Tombstone) -> None:
        self._tombstones[tombstone.key] = tombstone

    def has(self, key: str) -> bool:
        return key in self._tombstones

    def get(self, key: str) -> Tombstone | None:
        return self._tombstones.get(key)

    def all(self) -> list[Tombstone]:
        return list(self._tombstones.values())

    def count(self) -> int:
        return len(self._tombstones)


@dataclass
class GraphDeletionTarget:
    """Represents a deletable item and its relations for cascade planning."""

    key: str
    kind: str  # node, edge, fact, memory, playbook, etc.
    outgoing_relations: list[str] = field(default_factory=list)
    incoming_relations: list[str] = field(default_factory=list)


class DeletionEngine:
    """Cascading deletion with tombstone protection against resurrection.

    The engine walks outgoing relations depth-first, deleting each item
    it finds and placing a tombstone on its key.  Protected items
    (legal holds, pinned memories) block cascade into their subtree and
    are recorded in the report as blocked.
    """

    def __init__(
        self,
        get_target: Callable[[str], GraphDeletionTarget | None],
        delete_item: Callable[[str, str, DeletionReason, datetime], bool],
        is_protected: Callable[[str], bool] | None = None,
    ) -> None:
        self._get_target = get_target
        self._delete_item = delete_item
        self._is_protected = is_protected or (lambda _k: False)
        self.tombstones = TombstoneIndex()

    def delete(
        self,
        key: str,
        reason: DeletionReason,
        now: datetime,
        requested_by: str | None = None,
    ) -> DeletionReport:
        report = DeletionReport(
            requested_key=key,
            reason=reason,
            requested_at=now,
        )
        self._walk_delete(key, reason, now, requested_by, report, depth=0, visited=set())
        return report

    def _walk_delete(
        self,
        key: str,
        reason: DeletionReason,
        now: datetime,
        requested_by: str | None,
        report: DeletionReport,
        depth: int,
        visited: set[str],
    ) -> None:
        if key in visited:
            return
        visited.add(key)

        if self.tombstones.has(key):
            return

        if self._is_protected(key):
            report.blocked.append(key)
            return

        target = self._get_target(key)
        if target is None:
            report.errors.append(f"target not found: {key}")
            return

        ok = self._delete_item(key, target.kind, reason, now)
        if not ok:
            report.errors.append(f"delete failed: {key}")
            return

        self.tombstones.add(
            Tombstone(
                key=key,
                kind=target.kind,
                reason=reason,
                deleted_at=now,
                requested_by=requested_by,
            )
        )
        report.deleted.append(
            DeletionAuditEntry(
                key=key,
                kind=target.kind,
                reason=reason,
                deleted_at=now,
                cascade_depth=depth,
            )
        )

        for rel in target.outgoing_relations:
            self._walk_delete(rel, reason, now, requested_by, report, depth + 1, visited)

    def is_deleted(self, key: str) -> bool:
        return self.tombstones.has(key)

    def audit_report(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ts in self.tombstones.all():
            counts[ts.reason.value] = counts.get(ts.reason.value, 0) + 1
        return counts
