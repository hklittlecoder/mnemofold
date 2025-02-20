"""Proactive trigger system.

Rules derived from commitments, deadlines, and stale threads fire at
appropriate times.  Supports quiet hours, per-trigger cooldown and
deduplication windows, and suppression when a report already covers
an item.  Trigger logs are deterministic and replayable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


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
