"""Inbox triage: priority scoring for incoming items.

Priority scoring from deadline proximity, sender importance, thread
staleness, explicit asks, and commitment language. Provides per-item
reasons, batch and quiet-hour rules, and precision@k against planted labels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from mnemofold.graph import WorkstreamGraph


class TriagePriority(StrEnum):
    """Priority levels for triaged items."""

    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass(slots=True)
class TriageItem:
    """An item to be triaged (email, message, task, etc.)."""

    item_id: str
    title: str
    sender: str
    received_at: str
    content: str = ""
    has_deadline: bool = False
    deadline: str = ""
    has_explicit_ask: bool = False
    mentions_commitment: bool = False
    thread_length: int = 1
    thread_staleness_hours: float = 0.0
    sender_importance: float = 0.5  # 0.0 to 1.0
    tags: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TriageResult:
    """Result of triaging an item."""

    item_id: str
    score: float  # 0.0 to 1.0
    priority: TriagePriority
    reasons: list[str] = field(default_factory=list)


def _parse_dt(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


@dataclass
class TriageScorer:
    """Scores items for inbox triage priority."""

    deadline_weight: float = 0.30
    sender_weight: float = 0.20
    ask_weight: float = 0.20
    commitment_weight: float = 0.15
    staleness_weight: float = 0.10
    thread_weight: float = 0.05

    urgency_threshold: float = 0.8
    high_threshold: float = 0.6
    low_threshold: float = 0.25

    def score(self, item: TriageItem, now: str) -> TriageResult:
        """Score a single triage item."""
        reasons: list[str] = []
        score = 0.0
        total_weight = 0.0

        # Deadline proximity
        dl_score = self._deadline_score(item, now)
        if dl_score > 0:
            reasons.append(f"deadline_proximity={dl_score:.2f}")
        score += dl_score * self.deadline_weight
        total_weight += self.deadline_weight

        # Sender importance
        si_score = item.sender_importance
        if si_score > 0.5:
            reasons.append(f"sender_importance={si_score:.2f}")
        score += si_score * self.sender_weight
        total_weight += self.sender_weight

        # Explicit ask
        ask_score = 1.0 if item.has_explicit_ask else 0.0
        if ask_score > 0:
            reasons.append("explicit_ask")
        score += ask_score * self.ask_weight
        total_weight += self.ask_weight

        # Commitment mention
        comm_score = 1.0 if item.mentions_commitment else 0.0
        if comm_score > 0:
            reasons.append("mentions_commitment")
        score += comm_score * self.commitment_weight
        total_weight += self.commitment_weight

        # Thread staleness (lower staleness = higher priority for fresh threads)
        staleness_score = max(0.0, 1.0 - min(1.0, item.thread_staleness_hours / 48.0))
        score += staleness_score * self.staleness_weight
        total_weight += self.staleness_weight

        # Thread length (longer threads get slight boost)
        thread_score = min(1.0, item.thread_length / 10.0)
        score += thread_score * self.thread_weight
        total_weight += self.thread_weight

        # Normalize
        if total_weight > 0:
            score = score / total_weight
        score = max(0.0, min(1.0, score))

        priority = self._classify(score)

        return TriageResult(item_id=item.item_id, score=score, priority=priority, reasons=reasons)

    def _classify(self, score: float) -> TriagePriority:
        """Map a score to a priority band with the configured thresholds."""
        if score >= self.urgency_threshold:
            return TriagePriority.URGENT
        if score >= self.high_threshold:
            return TriagePriority.HIGH
        if score <= self.low_threshold:
            return TriagePriority.LOW
        return TriagePriority.NORMAL

    def _deadline_score(self, item: TriageItem, now: str) -> float:
        if not item.has_deadline or not item.deadline:
            return 0.0
        t_deadline = _parse_dt(item.deadline)
        t_now = _parse_dt(now)
        if t_deadline is None or t_now is None:
            return 0.0
        hours_left = (t_deadline - t_now).total_seconds() / 3600.0
        if hours_left <= 0:
            return 1.0  # overdue = max priority
        # Exponential: 1.0 at 0h, ~0.5 at 24h, ~0.1 at 72h
        return float(math.exp(-hours_left / 24.0))

    def batch_score(self, items: list[TriageItem], now: str) -> list[TriageResult]:
        """Score a batch of items, sorted by score descending."""
        results = [self.score(item, now) for item in items]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def apply_quiet_hours(
        self,
        results: list[TriageResult],
        quiet_start_hour: int = 20,
        quiet_end_hour: int = 7,
        now: str = "",
    ) -> list[TriageResult]:
        """Reduce priority for non-urgent items during quiet hours."""
        if not now:
            return results
        dt = _parse_dt(now)
        if dt is None:
            return results
        hour = dt.hour
        in_quiet = (hour >= quiet_start_hour) or (hour < quiet_end_hour)
        if not in_quiet:
            return results
        modified: list[TriageResult] = []
        for r in results:
            if r.priority == TriagePriority.URGENT:
                modified.append(r)
                continue
            # Recompute the band from the reduced score: keeping the old
            # priority left score and band inconsistent (a 0.4 score
            # labeled HIGH), which distorted downstream batching.
            reduced = max(0.0, r.score - 0.3)
            new_r = TriageResult(
                item_id=r.item_id,
                score=reduced,
                priority=self._classify(reduced),
                reasons=[*r.reasons, "quiet_hours_reduced"],
            )
            modified.append(new_r)
        modified.sort(key=lambda r: r.score, reverse=True)
        return modified


def precision_at_k(results: list[TriageResult], labels: dict[str, bool], k: int) -> float:
    """Compute precision@k against planted labels.

    labels maps item_id -> True (should be high priority) or False.
    Returns the fraction of top-k items that are true positives.
    """
    if k <= 0 or not results:
        return 0.0
    top_k = results[:k]
    relevant = sum(1 for r in top_k if labels.get(r.item_id, False))
    return relevant / len(top_k)


# --- Graph-derived sender importance -------------------------------------------


def sender_degrees(graph: WorkstreamGraph) -> dict[str, int]:
    """Active-edge degree per node id, counting both directions."""
    degrees: dict[str, int] = {}
    for node_id in sorted(graph.nodes):
        degrees[node_id] = len(graph.outgoing_edges(node_id)) + len(graph.incoming_edges(node_id))
    return degrees


def attach_graph_importance(items: list[TriageItem], graph: WorkstreamGraph) -> None:
    """Set sender_importance in place from relative graph connectivity.

    ``importance = 0.2 + 0.8 * degree / max_degree``, quantized to six
    decimals. Senders absent from the graph keep their current value (the
    neutral default), so unknown people are neither boosted nor punished.
    Deterministic for identical graphs and item lists.
    """
    degrees = sender_degrees(graph)
    max_degree = max(degrees.values()) if degrees else 0
    if max_degree <= 0:
        return
    for item in items:
        degree = degrees.get(item.sender)
        if degree is not None:
            item.sender_importance = round(0.2 + 0.8 * degree / max_degree, 6)


# --- Batching rules -------------------------------------------------------------


@dataclass(slots=True)
class BatchPlan:
    """Bucketed triage output after applying caps.

    Every scored result lands in exactly one bucket, so
    ``total() == len(input)`` always holds — batching re-routes items,
    it never drops them.
    """

    act_now: list[TriageResult] = field(default_factory=list)
    review: list[TriageResult] = field(default_factory=list)
    defer: list[TriageResult] = field(default_factory=list)

    def total(self) -> int:
        return len(self.act_now) + len(self.review) + len(self.defer)


@dataclass
class TriageBatcher:
    """Deterministic batching rules on top of scored results.

    * ``act_now``: URGENT results up to ``max_act_now``; overflow keeps
      its score but moves to ``review`` and gains a ``batch_overflow``
      reason;
    * ``review``: URGENT overflow plus HIGH/NORMAL results up to
      ``max_review``; overflow moves to ``defer`` (also marked);
    * ``defer``: LOW results and any overflow.

    Input order is preserved inside each bucket, so callers should pass
    score-sorted results (e.g. from :meth:`TriageScorer.batch_score`).
    """

    max_act_now: int = 3
    max_review: int = 10

    def batch(self, results: list[TriageResult]) -> BatchPlan:
        plan = BatchPlan()
        for result in results:
            if result.priority == TriagePriority.URGENT and len(plan.act_now) < self.max_act_now:
                plan.act_now.append(result)
                continue
            if result.priority in (
                TriagePriority.URGENT,
                TriagePriority.HIGH,
                TriagePriority.NORMAL,
            ):
                if len(plan.review) < self.max_review:
                    if result.priority == TriagePriority.URGENT:
                        result.reasons.append("batch_overflow")
                    plan.review.append(result)
                else:
                    result.reasons.append("batch_overflow")
                    plan.defer.append(result)
                continue
            plan.defer.append(result)
        return plan
