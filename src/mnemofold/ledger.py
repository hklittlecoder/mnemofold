"""Commitment ledger: track commitments with status and deadlines.

Commitments represent who owes whom what by when. Supports status
transitions, overdue detection with grace windows, nudges, and
deterministic Markdown/JSON export.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CommitmentStatus(StrEnum):
    """Status of a commitment."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


# Valid transitions: from -> set of allowed next statuses
VALID_TRANSITIONS: dict[CommitmentStatus, set[CommitmentStatus]] = {
    CommitmentStatus.OPEN: {
        CommitmentStatus.IN_PROGRESS,
        CommitmentStatus.DONE,
        CommitmentStatus.CANCELLED,
        CommitmentStatus.SUPERSEDED,
    },
    CommitmentStatus.IN_PROGRESS: {
        CommitmentStatus.DONE,
        CommitmentStatus.CANCELLED,
        CommitmentStatus.SUPERSEDED,
        CommitmentStatus.OPEN,
    },
    CommitmentStatus.DONE: set(),
    CommitmentStatus.CANCELLED: set(),
    CommitmentStatus.SUPERSEDED: set(),
}


@dataclass(slots=True)
class Commitment:
    """A commitment: who owes whom what by when."""

    commitment_id: str
    owed_by: str
    owed_to: str
    description: str
    due_date: str  # ISO datetime
    status: CommitmentStatus = CommitmentStatus.OPEN
    priority: float = 0.5
    created_at: str = ""
    updated_at: str = ""
    source_event_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # other commitment IDs
    tags: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    grace_hours: float = 0.0  # per-commitment grace window for overdue checks

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = CommitmentStatus(self.status)
        if isinstance(self.tags, list):
            self.tags = set(self.tags)

    def can_transition_to(self, new_status: CommitmentStatus) -> bool:
        """Check if a status transition is valid."""
        if isinstance(new_status, str):
            new_status = CommitmentStatus(new_status)
        return new_status in VALID_TRANSITIONS.get(self.status, set())

    def is_overdue(self, now: str, grace_hours: float | None = None) -> bool:
        """Check if this commitment is overdue.

        ``grace_hours=None`` uses the commitment's own grace window; an
        explicit argument overrides it for this call only.
        """
        if self.status in {
            CommitmentStatus.DONE,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.SUPERSEDED,
        }:
            return False
        try:
            from datetime import timedelta

            t_due = datetime.fromisoformat(self.due_date)
            t_now = datetime.fromisoformat(now)
            if t_due.tzinfo is None:
                t_due = t_due.replace(tzinfo=UTC)
            if t_now.tzinfo is None:
                t_now = t_now.replace(tzinfo=UTC)
            effective_grace = self.grace_hours if grace_hours is None else grace_hours
            return t_now > t_due + timedelta(hours=effective_grace)
        except (ValueError, TypeError):
            return False

    def days_until_due(self, now: str) -> float | None:
        """Days until due date (negative if overdue)."""
        try:
            t_due = datetime.fromisoformat(self.due_date)
            t_now = datetime.fromisoformat(now)
            if t_due.tzinfo is None:
                t_due = t_due.replace(tzinfo=UTC)
            if t_now.tzinfo is None:
                t_now = t_now.replace(tzinfo=UTC)
            return (t_due - t_now).total_seconds() / 86400.0
        except (ValueError, TypeError):
            return None


@dataclass(slots=True)
class Nudge:
    """A deterministic reminder suggestion for one commitment."""

    commitment_id: str
    owed_by: str
    kind: str  # upcoming | overdue
    due_date: str
    message: str


@dataclass
class CommitmentLedger:
    """A ledger of commitments with tracking and querying."""

    _commitments: dict[str, Commitment] = field(default_factory=dict)
    _history: list[dict[str, Any]] = field(default_factory=list)  # transition history

    def add(self, commitment: Commitment) -> None:
        """Add a commitment to the ledger."""
        self._commitments[commitment.commitment_id] = commitment
        self._history.append(
            {
                "commitment_id": commitment.commitment_id,
                "action": "created",
                "from_status": None,
                "to_status": str(commitment.status),
                "timestamp": commitment.created_at or "",
            }
        )

    def get(self, commitment_id: str) -> Commitment | None:
        """Get a commitment by ID."""
        return self._commitments.get(commitment_id)

    def transition(self, commitment_id: str, new_status: CommitmentStatus, timestamp: str) -> bool:
        """Transition a commitment to a new status. Returns True on success."""
        c = self._commitments.get(commitment_id)
        if c is None:
            return False
        if not c.can_transition_to(new_status):
            return False
        old_status = c.status
        c.status = CommitmentStatus(new_status) if isinstance(new_status, str) else new_status
        c.updated_at = timestamp
        self._history.append(
            {
                "commitment_id": commitment_id,
                "action": "status_change",
                "from_status": str(old_status),
                "to_status": str(c.status),
                "timestamp": timestamp,
            }
        )
        return True

    def overdue(self, now: str, grace_hours: float | None = None) -> list[Commitment]:
        """Return all overdue commitments (per-commitment grace by default)."""
        return [c for c in self._commitments.values() if c.is_overdue(now, grace_hours)]

    def by_status(self, status: CommitmentStatus) -> list[Commitment]:
        """Return commitments with a given status."""
        if isinstance(status, str):
            status = CommitmentStatus(status)
        return [c for c in self._commitments.values() if c.status == status]

    def by_owed_by(self, person: str) -> list[Commitment]:
        """Return commitments owed by a person."""
        return [c for c in self._commitments.values() if c.owed_by == person]

    def by_owed_to(self, person: str) -> list[Commitment]:
        """Return commitments owed to a person."""
        return [c for c in self._commitments.values() if c.owed_to == person]

    def upcoming(self, now: str, days: float = 7.0) -> list[Commitment]:
        """Return active commitments due within 'days' days."""
        result: list[Commitment] = []
        for c in self._commitments.values():
            if c.status in {
                CommitmentStatus.DONE,
                CommitmentStatus.CANCELLED,
                CommitmentStatus.SUPERSEDED,
            }:
                continue
            d = c.days_until_due(now)
            if d is not None and d <= days:
                result.append(c)
        result.sort(key=lambda c: c.due_date)
        return result

    def total_count(self) -> int:
        return len(self._commitments)

    def transition_history(self) -> list[dict[str, Any]]:
        """Return the full transition history."""
        return list(self._history)

    def to_json(self, indent: int = 2) -> str:
        """Export the ledger as JSON."""
        data = {
            "commitments": [
                {
                    "commitment_id": c.commitment_id,
                    "owed_by": c.owed_by,
                    "owed_to": c.owed_to,
                    "description": c.description,
                    "due_date": c.due_date,
                    "status": str(c.status),
                    "priority": c.priority,
                    "grace_hours": round(c.grace_hours, 6),
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                    "source_event_ids": list(c.source_event_ids),
                    "depends_on": list(c.depends_on),
                    "tags": sorted(c.tags),
                    "metadata": c.metadata,
                }
                for c in sorted(self._commitments.values(), key=lambda x: x.commitment_id)
            ],
            "history": self._history,
        }
        return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=True)

    def to_markdown(self) -> str:
        """Export the ledger as Markdown."""
        lines = ["# Commitment Ledger", ""]
        by_status: dict[str, list[Commitment]] = {}
        for c in self._commitments.values():
            by_status.setdefault(str(c.status), []).append(c)
        for status_name in sorted(by_status.keys()):
            items = sorted(by_status[status_name], key=lambda c: c.due_date)
            lines.append(f"## {status_name.replace('_', ' ').title()} ({len(items)})")
            lines.append("")
            for c in items:
                lines.append(f"### {c.description}")
                lines.append(f"- **ID**: `{c.commitment_id}`")
                lines.append(f"- **Owed by**: {c.owed_by} → **Owed to**: {c.owed_to}")
                lines.append(f"- **Due**: {c.due_date}")
                lines.append(f"- **Priority**: {c.priority:.2f}")
                if c.tags:
                    lines.append(f"- **Tags**: {', '.join(sorted(c.tags))}")
                lines.append("")
        return "\n".join(lines)

    def nudges(self, now: str, ahead_days: float = 2.0) -> list[Nudge]:
        """Reminder suggestions for active commitments, deterministically ordered.

        Kinds: ``overdue`` (past due including the commitment's own grace
        window) and ``upcoming`` (due within ``ahead_days`` from now).
        Items inside their grace window are not nudged. Sorted by
        (due_date, commitment_id).
        """
        closed = {
            CommitmentStatus.DONE,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.SUPERSEDED,
        }
        out: list[Nudge] = []
        for commitment_id in sorted(self._commitments):
            c = self._commitments[commitment_id]
            if c.status in closed:
                continue
            if c.is_overdue(now):
                kind = "overdue"
                message = f"Overdue: {c.description} (was due {c.due_date})"
            else:
                days_left = c.days_until_due(now)
                if days_left is None or days_left < 0 or days_left > ahead_days:
                    continue
                kind = "upcoming"
                message = f"Due soon: {c.description} (due {c.due_date})"
            out.append(
                Nudge(
                    commitment_id=c.commitment_id,
                    owed_by=c.owed_by,
                    kind=kind,
                    due_date=c.due_date,
                    message=message,
                )
            )
        out.sort(key=lambda n: (n.due_date, n.commitment_id))
        return out
