"""Proactive trigger system.

Rules derived from commitments, deadlines, and stale threads fire at
appropriate times.  Supports quiet hours, per-trigger cooldown and
deduplication windows, and suppression when a report already covers
an item.  Trigger logs are deterministic and replayable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from mnemofold.events import Event
from mnemofold.ledger import CommitmentLedger, CommitmentStatus


class TriggerKind(StrEnum):
    DEADLINE_REMINDER = "deadline_reminder"
    OVERDUE_ALERT = "overdue_alert"
    STALE_THREAD = "stale_thread"
    FOLLOW_UP = "follow_up"
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_REVIEW = "weekly_review"


class TriggerSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class TriggerRule:
    rule_id: str
    kind: TriggerKind
    target_id: str
    fire_at: datetime
    severity: TriggerSeverity = TriggerSeverity.INFO
    message: str = ""
    cooldown: timedelta | None = None
    dedupe_window: timedelta | None = None


@dataclass(slots=True)
class FiredTrigger:
    rule_id: str
    kind: TriggerKind
    target_id: str
    fired_at: datetime
    severity: TriggerSeverity
    message: str
    suppressed: bool = False
    suppress_reason: str = ""


class QuietHours:
    """Defines a quiet period during which low-severity triggers are suppressed."""

    def __init__(
        self,
        start_hour: int = 22,
        end_hour: int = 7,
        suppress_severity_below: TriggerSeverity = TriggerSeverity.CRITICAL,
    ) -> None:
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.suppress_severity_below = suppress_severity_below

    def is_quiet(self, when: datetime) -> bool:
        hour = when.hour
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    def suppresses(self, severity: TriggerSeverity, when: datetime) -> bool:
        if not self.is_quiet(when):
            return False
        order = {TriggerSeverity.INFO: 0, TriggerSeverity.WARNING: 1, TriggerSeverity.CRITICAL: 2}
        return order[severity] < order[self.suppress_severity_below]


class TriggerEngine:
    """Evaluates trigger rules and produces fired-trigger logs.

    Supports cooldowns (same rule can fire only once per cooldown
    window), deduplication (same target+kind is suppressed within a
    window), quiet-hours suppression, and coverage-based suppression
    when a supplied report already mentions the target.
    """

    def __init__(
        self,
        quiet_hours: QuietHours | None = None,
        is_covered_by_report: Callable[[str, TriggerKind], bool] | None = None,
    ) -> None:
        self.quiet_hours = quiet_hours
        self._is_covered = is_covered_by_report or (lambda _tid, _k: False)
        self._rules: list[TriggerRule] = []
        self._fired: list[FiredTrigger] = []
        self._last_fire: dict[str, datetime] = {}
        self._last_dedupe: dict[tuple[str, TriggerKind], datetime] = {}

    def add_rule(self, rule: TriggerRule) -> None:
        self._rules.append(rule)

    def rules(self) -> list[TriggerRule]:
        return list(self._rules)

    def fired(self) -> list[FiredTrigger]:
        return list(self._fired)

    def tick(self, now: datetime) -> list[FiredTrigger]:
        """Evaluate all rules and fire those due; return newly fired triggers."""
        newly_fired: list[FiredTrigger] = []
        for rule in self._rules:
            if now < rule.fire_at:
                continue

            # Cooldown check
            if rule.cooldown and rule.rule_id in self._last_fire:
                last = self._last_fire[rule.rule_id]
                if now < last + rule.cooldown:
                    continue

            # Dedupe check
            dedupe_key = (rule.target_id, rule.kind)
            if rule.dedupe_window and dedupe_key in self._last_dedupe:
                last = self._last_dedupe[dedupe_key]
                if now < last + rule.dedupe_window:
                    continue

            # Quiet hours check
            if self.quiet_hours and self.quiet_hours.suppresses(rule.severity, now):
                fired = FiredTrigger(
                    rule_id=rule.rule_id,
                    kind=rule.kind,
                    target_id=rule.target_id,
                    fired_at=now,
                    severity=rule.severity,
                    message=rule.message,
                    suppressed=True,
                    suppress_reason="quiet_hours",
                )
                self._fired.append(fired)
                self._last_fire[rule.rule_id] = now
                self._last_dedupe[dedupe_key] = now
                newly_fired.append(fired)
                continue

            # Report coverage check
            if self._is_covered(rule.target_id, rule.kind):
                fired = FiredTrigger(
                    rule_id=rule.rule_id,
                    kind=rule.kind,
                    target_id=rule.target_id,
                    fired_at=now,
                    severity=rule.severity,
                    message=rule.message,
                    suppressed=True,
                    suppress_reason="covered_by_report",
                )
                self._fired.append(fired)
                self._last_fire[rule.rule_id] = now
                self._last_dedupe[dedupe_key] = now
                newly_fired.append(fired)
                continue

            fired = FiredTrigger(
                rule_id=rule.rule_id,
                kind=rule.kind,
                target_id=rule.target_id,
                fired_at=now,
                severity=rule.severity,
                message=rule.message,
            )
            self._fired.append(fired)
            self._last_fire[rule.rule_id] = now
            self._last_dedupe[dedupe_key] = now
            newly_fired.append(fired)

        return newly_fired

    def active_triggers(self) -> list[FiredTrigger]:
        """Return all non-suppressed fired triggers."""
        return [f for f in self._fired if not f.suppressed]

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self._fired:
            key = f.kind.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def summary_report(self) -> dict[str, Any]:
        """Deterministic summary of all trigger activity.

        Breaks down total fired, active (non-suppressed), and suppressed
        counts by kind, severity, and suppression reason. Floats are not
        produced here — all values are counts so the report is stable
        across runs with the same inputs.
        """
        total = len(self._fired)
        active = sum(1 for f in self._fired if not f.suppressed)
        suppressed = total - active
        by_kind: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_suppress_reason: dict[str, int] = {}
        for f in self._fired:
            k = f.kind.value
            by_kind[k] = by_kind.get(k, 0) + 1
            s = f.severity.value
            by_severity[s] = by_severity.get(s, 0) + 1
            if f.suppressed and f.suppress_reason:
                r = f.suppress_reason
                by_suppress_reason[r] = by_suppress_reason.get(r, 0) + 1
        return {
            "total_fired": total,
            "active": active,
            "suppressed": suppressed,
            "by_kind": dict(sorted(by_kind.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "by_suppress_reason": dict(sorted(by_suppress_reason.items())),
        }


# --- Persistent trigger log -----------------------------------------------------


def fired_to_dict(fired: FiredTrigger) -> dict[str, Any]:
    return {
        "rule_id": fired.rule_id,
        "kind": fired.kind.value,
        "target_id": fired.target_id,
        "fired_at": fired.fired_at.isoformat(),
        "severity": fired.severity.value,
        "message": fired.message,
        "suppressed": fired.suppressed,
        "suppress_reason": fired.suppress_reason,
    }


def fired_from_dict(data: dict[str, Any]) -> FiredTrigger:
    return FiredTrigger(
        rule_id=data["rule_id"],
        kind=TriggerKind(data["kind"]),
        target_id=data["target_id"],
        fired_at=datetime.fromisoformat(data["fired_at"]),
        severity=TriggerSeverity(data["severity"]),
        message=data.get("message", ""),
        suppressed=data.get("suppressed", False),
        suppress_reason=data.get("suppress_reason", ""),
    )


def write_trigger_log(path: str | Path, fired: list[FiredTrigger]) -> None:
    """Write fired triggers as a checksummed JSONL log (full rewrite).

    Each line carries a SHA-256 chained from the previous line, so any
    later edit, reorder, or truncation of the log is detectable on read.
    Identical input always produces identical bytes.
    """
    lines: list[str] = []
    prev = "0" * 64
    for trigger in fired:
        entry = fired_to_dict(trigger)
        digest = hashlib.sha256(
            (prev + "\n" + json.dumps(entry, sort_keys=True)).encode()
        ).hexdigest()
        lines.append(json.dumps({"hash": digest, "entry": entry}, sort_keys=True))
        prev = digest
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def read_trigger_log(path: str | Path) -> list[FiredTrigger]:
    """Read a trigger log, verifying every chained hash.

    Raises ValueError when the chain does not verify.
    """
    prev = "0" * 64
    out: list[FiredTrigger] = []
    text = Path(path).read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        expected = hashlib.sha256(
            (prev + "\n" + json.dumps(obj["entry"], sort_keys=True)).encode()
        ).hexdigest()
        if obj["hash"] != expected:
            raise ValueError(f"trigger log corrupt at line {lineno}")
        prev = obj["hash"]
        out.append(fired_from_dict(obj["entry"]))
    return out


def derive_commitment_rules(
    ledger: CommitmentLedger,
    now: datetime,
    *,
    ahead_days: float = 2.0,
    cooldown_hours: float = 12.0,
) -> list[TriggerRule]:
    """Build reminder rules from open ledger commitments.

    Each open or in-progress commitment yields exactly one rule with a
    deterministic id (``trg-<commitment_id>``): an overdue commitment
    becomes a CRITICAL ``OVERDUE_ALERT`` due immediately, otherwise a
    WARNING ``DEADLINE_REMINDER`` fires ``ahead_days`` before the due
    date (clamped to ``now`` so it never lies in the past). Terminal
    commitments and commitments without a parseable due date are
    skipped. Re-deriving after a rebuild gives the same rule set.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    rules: list[TriggerRule] = []
    cooldown = timedelta(hours=cooldown_hours)
    for commitment in sorted(ledger.all_commitments(), key=lambda c: c.commitment_id):
        if commitment.status in {
            CommitmentStatus.DONE,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.SUPERSEDED,
        }:
            continue
        try:
            due = datetime.fromisoformat(commitment.due_date)
        except (ValueError, TypeError):
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        if commitment.is_overdue(now.isoformat()):
            kind = TriggerKind.OVERDUE_ALERT
            severity = TriggerSeverity.CRITICAL
            fire_at = now
            message = f"commitment {commitment.commitment_id} is overdue since {due.isoformat()}"
        else:
            kind = TriggerKind.DEADLINE_REMINDER
            severity = TriggerSeverity.WARNING
            fire_at = max(due - timedelta(days=ahead_days), now)
            message = f"commitment {commitment.commitment_id} is due at {due.isoformat()}"
        rules.append(
            TriggerRule(
                rule_id=f"trg-{commitment.commitment_id}",
                kind=kind,
                target_id=commitment.commitment_id,
                fire_at=fire_at,
                severity=severity,
                message=message,
                cooldown=cooldown,
                dedupe_window=cooldown,
            )
        )
    return rules


def thread_activity(events: list[Event]) -> dict[str, list[Event]]:
    """Events per thread id, in timestamp order — the shared thread scan.

    Events without a ``thread_id`` are ignored; non-string ids are
    normalized with ``str``. Ties on identical timestamps are broken by
    ``event_id`` so the ordering is total regardless of input order.
    Derivation helpers build on this so "what happened in thread T" has
    exactly one definition.
    """
    ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id))
    threads: dict[str, list[Event]] = {}
    for event in ordered:
        tid = event.content.get("thread_id")
        if tid is not None:
            threads.setdefault(str(tid), []).append(event)
    return threads


def derive_stale_thread_rules(
    events: list[Event],
    now: datetime,
    *,
    stale_after_days: float = 3.0,
    closed_after_days: float | None = None,
    cooldown_hours: float = 24.0,
) -> list[TriggerRule]:
    """Build STALE_THREAD rules for threads that went quiet.

    A thread whose most recent event is at least ``stale_after_days``
    old — but younger than ``closed_after_days`` (default: twice
    ``stale_after_days``) — yields one WARNING rule firing at ``now``
    with a deterministic id (``trg-thread-<thread_id>``). Threads quiet
    past the closed horizon count as settled and are skipped: nag about
    recent silence, not ancient history. Events without a ``thread_id``
    are ignored and a naive ``now`` is treated as UTC. Re-deriving from
    the same inputs gives the same rule set.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    closed_after = closed_after_days if closed_after_days is not None else 2.0 * stale_after_days
    last_seen = {tid: evs[-1].timestamp for tid, evs in thread_activity(events).items()}
    cooldown = timedelta(hours=cooldown_hours)
    rules: list[TriggerRule] = []
    for tid in sorted(last_seen):
        age_days = (now - last_seen[tid]).total_seconds() / 86400.0
        if age_days < stale_after_days or age_days >= closed_after:
            continue
        rules.append(
            TriggerRule(
                rule_id=f"trg-thread-{tid}",
                kind=TriggerKind.STALE_THREAD,
                target_id=tid,
                fire_at=now,
                severity=TriggerSeverity.WARNING,
                message=(
                    f"thread {tid} quiet since {last_seen[tid].isoformat()} "
                    f"({round(age_days, 1)} days)"
                ),
                cooldown=cooldown,
                dedupe_window=cooldown,
            )
        )
    return rules
