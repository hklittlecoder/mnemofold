"""Commitment ledger: track commitments with status and deadlines.

Commitments represent who owes whom what by when. Supports status
transitions, overdue detection with grace windows, nudges, and
deterministic Markdown/JSON export.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
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
    kind: str  # upcoming | overdue | blocked
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

    def all_commitments(self) -> list[Commitment]:
        """All commitments ordered by (due_date, commitment_id)."""
        return sorted(self._commitments.values(), key=lambda c: (c.due_date, c.commitment_id))

    def remove(self, commitment_id: str) -> bool:
        """Drop a commitment entirely (used when its source is forgotten).

        Unlike a status transition this removes the record; the removal
        is still visible in the transition history of the source event
        pipeline, and forgetting is recorded as a journal tombstone.
        """
        removed = self._commitments.pop(commitment_id, None)
        if removed is None:
            return False
        self._history.append(
            {
                "commitment_id": commitment_id,
                "action": "removed",
                "from_status": str(removed.status),
                "to_status": None,
                "timestamp": removed.updated_at,
            }
        )
        return True

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
        window), ``blocked`` (an unfinished dependency stands between the
        commitment and its due window), and ``upcoming`` (due within
        ``ahead_days``). Items inside their grace window are not nudged
        unless they are blocked. Sorted by (due_date, commitment_id).
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
            blocking = self.open_dependencies(c.commitment_id)
            days_left = c.days_until_due(now)
            if c.is_overdue(now):
                kind = "overdue"
                message = f"Overdue: {c.description} (was due {c.due_date})"
                if blocking:
                    message += f"; blocked by {', '.join(blocking)}"
            elif blocking and days_left is not None and days_left <= ahead_days:
                kind = "blocked"
                message = (
                    f"Blocked: {c.description} waits on {', '.join(blocking)} (due {c.due_date})"
                )
            elif days_left is not None and 0 <= days_left <= ahead_days:
                kind = "upcoming"
                message = f"Due soon: {c.description} (due {c.due_date})"
            else:
                continue
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

    @classmethod
    def from_json(cls, text: str) -> CommitmentLedger:
        """Rebuild a ledger from :meth:`to_json` output (both directions).

        History entries are restored verbatim and no new ``created``
        entries are appended, so export -> import -> export is stable.
        Unknown statuses raise, keeping imports as strict as exports.
        """
        data = json.loads(text)
        ledger = cls()
        for entry in data.get("commitments", []):
            commitment = Commitment(
                commitment_id=entry["commitment_id"],
                owed_by=entry["owed_by"],
                owed_to=entry["owed_to"],
                description=entry["description"],
                due_date=entry["due_date"],
                status=CommitmentStatus(entry["status"]),
                priority=entry.get("priority", 0.5),
                created_at=entry.get("created_at", ""),
                updated_at=entry.get("updated_at", ""),
                source_event_ids=list(entry.get("source_event_ids", [])),
                depends_on=list(entry.get("depends_on", [])),
                tags=set(entry.get("tags", [])),
                metadata=dict(entry.get("metadata", {})),
                grace_hours=entry.get("grace_hours", 0.0),
            )
            ledger._commitments[commitment.commitment_id] = commitment
        ledger._history = [dict(entry) for entry in data.get("history", [])]
        return ledger

    def open_dependencies(self, commitment_id: str) -> list[str]:
        """Dependency ids that are not finished yet, in depends_on order.

        Unknown dependency ids count as blocking: a reference we cannot
        verify is not a green light.
        """
        c = self._commitments.get(commitment_id)
        if c is None:
            return []
        finished = {
            CommitmentStatus.DONE,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.SUPERSEDED,
        }
        blocking: list[str] = []
        for dep in c.depends_on:
            dep_item = self._commitments.get(dep)
            if dep_item is None or dep_item.status not in finished:
                blocking.append(dep)
        return blocking

    def blocked_commitments(self) -> list[Commitment]:
        """Active commitments with at least one unfinished dependency."""
        active = {CommitmentStatus.OPEN, CommitmentStatus.IN_PROGRESS}
        return [
            self._commitments[cid]
            for cid in sorted(self._commitments)
            if self._commitments[cid].status in active and self.open_dependencies(cid)
        ]

    def aging_report(self, now: str) -> dict[str, Any]:
        """Bucket active commitments by due-time urgency.

        Active means OPEN or IN_PROGRESS. Buckets: ``overdue`` (past due
        outside the commitment's own grace window), ``due_today`` (under
        24h away, including negative offsets still covered by grace),
        ``due_this_week`` (1-7 days), ``later`` (7+ days) and ``no_due``
        (unparseable due date). Ids are sorted inside each bucket and
        the bucket sizes always sum to ``total_active``.
        """
        active_statuses = {CommitmentStatus.OPEN, CommitmentStatus.IN_PROGRESS}
        buckets: dict[str, list[str]] = {
            "overdue": [],
            "due_today": [],
            "due_this_week": [],
            "later": [],
            "no_due": [],
        }
        for cid in sorted(self._commitments):
            commitment = self._commitments[cid]
            if commitment.status not in active_statuses:
                continue
            if commitment.is_overdue(now):
                buckets["overdue"].append(cid)
                continue
            days = commitment.days_until_due(now)
            if days is None:
                buckets["no_due"].append(cid)
            elif days < 1.0:
                buckets["due_today"].append(cid)
            elif days < 7.0:
                buckets["due_this_week"].append(cid)
            else:
                buckets["later"].append(cid)
        counts = {name: len(ids) for name, ids in buckets.items()}
        return {
            "now": now,
            "total_active": sum(counts.values()),
            "counts": counts,
            **buckets,
        }

    def burndown_series(self, start_day: str, days: int) -> list[dict[str, Any]]:
        """Per-day cumulative (created, resolved, open) series for charts.

        ``created`` counts commitments whose creation day (``created_at``,
        falling back to ``updated_at``, falling back to ``start_day``
        when neither parses) is on or before the day; ``resolved`` counts
        DONE/CANCELLED/SUPERSEDED transitions recorded on or before it.
        Days are consecutive calendar dates from ``start_day``; both
        counters are non-decreasing, so the series renders directly as a
        burndown chart.
        """
        if days < 0:
            raise ValueError("days must be non-negative")
        start = date.fromisoformat(str(start_day)[:10])
        resolved_statuses = {
            str(CommitmentStatus.DONE),
            str(CommitmentStatus.CANCELLED),
            str(CommitmentStatus.SUPERSEDED),
        }
        created_days: list[date] = []
        for cid in sorted(self._commitments):
            created_days.append(self._created_day(self._commitments[cid], start))
        resolved_days: list[date] = []
        for entry in self._history:
            if (
                entry.get("action") == "status_change"
                and entry.get("to_status") in resolved_statuses
            ):
                resolved_days.append(self._parse_day(str(entry.get("timestamp", "")), start))
        series: list[dict[str, Any]] = []
        for i in range(days):
            day = start + timedelta(days=i)
            created = sum(1 for d in created_days if d <= day)
            resolved = sum(1 for d in resolved_days if d <= day)
            series.append(
                {
                    "day": day.isoformat(),
                    "created": created,
                    "resolved": resolved,
                    "open": created - resolved,
                }
            )
        return series

    @staticmethod
    def _parse_day(value: str, fallback: date) -> date:
        """First 10 chars as a date; fallback when unparseable."""
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return fallback

    @classmethod
    def _created_day(cls, commitment: Commitment, fallback: date) -> date:
        """Creation day with updated_at and start_day fallbacks."""
        for candidate in (commitment.created_at, commitment.updated_at):
            if candidate:
                try:
                    return date.fromisoformat(candidate[:10])
                except ValueError:
                    continue
        return fallback

    def verify_history(self) -> dict[str, Any]:
        """Recompute commitment statuses from the transition history.

        Replays ``created`` and ``status_change`` entries in order and
        compares each reconstructed final status with the live one.
        ``ok`` is True when the live ledger is exactly what its history
        implies — an internal-consistency audit that catches corrupted
        state and buggy transitions alike. Commitments that appear only
        in history (e.g. removed via right-to-be-forgotten) are listed
        under ``history_only`` for transparency but do not affect ``ok``.
        """
        replayed: dict[str, str] = {}
        for entry in self._history:
            cid = str(entry.get("commitment_id", ""))
            action = entry.get("action")
            if action == "created":
                replayed.setdefault(cid, str(entry.get("to_status", "open")))
            elif action == "status_change":
                replayed[cid] = str(entry.get("to_status", ""))
        mismatches: list[dict[str, str]] = []
        for cid in sorted(self._commitments):
            expected = replayed.get(cid)
            actual = str(self._commitments[cid].status)
            if expected != actual:
                mismatches.append(
                    {
                        "commitment_id": cid,
                        "history_says": expected if expected is not None else "(missing)",
                        "live": actual,
                    }
                )
        live_ids = set(self._commitments)
        return {
            "ok": not mismatches,
            "mismatches": mismatches,
            "history_entries": len(self._history),
            "replayed_statuses": {cid: replayed[cid] for cid in sorted(replayed)},
            "history_only": sorted(cid for cid in replayed if cid not in live_ids),
        }
