"""Evaluation harness for mnemofold.

End-to-end persona scenarios scored against planted ground truth:
commitment recall/precision, overdue-detection accuracy, as-of query
correctness, triage precision@k, meeting-prep coverage, stale-fact
avoidance, citation validity, budget adherence, privacy-violation
counters (must be zero), deletion-resurrection checks, and replay
determinism double-run.  Per-slice and aggregate scorecards with
golden tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MetricStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class MetricResult:
    name: str
    value: float
    threshold: float | None = None
    higher_is_better: bool = True
    status: MetricStatus = MetricStatus.PASS

    def __post_init__(self) -> None:
        if self.threshold is not None:
            if self.higher_is_better:
                self.status = (
                    MetricStatus.PASS if self.value >= self.threshold else MetricStatus.FAIL
                )
            else:
                self.status = (
                    MetricStatus.PASS if self.value <= self.threshold else MetricStatus.FAIL
                )


@dataclass
class Scorecard:
    scenario: str
    metrics: list[MetricResult] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def add(self, metric: MetricResult) -> None:
        self.metrics.append(metric)

    def pass_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == MetricStatus.PASS)

    def fail_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == MetricStatus.FAIL)

    def overall_pass(self) -> bool:
        return self.fail_count() == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "overall_pass": self.overall_pass(),
            "pass_count": self.pass_count(),
            "fail_count": self.fail_count(),
            "total_metrics": len(self.metrics),
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "threshold": m.threshold,
                    "higher_is_better": m.higher_is_better,
                    "status": m.status.value,
                }
                for m in self.metrics
            ],
            "details": self.details,
        }


def precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Compute precision@k: fraction of top-k items that are relevant."""
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in relevant)
    return round(hits / len(top_k), 6)


def recall(relevant: set[str], retrieved: set[str]) -> float:
    """Compute recall: fraction of relevant items that were retrieved."""
    if not relevant:
        return 1.0
    hits = len(relevant & retrieved)
    return round(hits / len(relevant), 6)


def precision(relevant: set[str], retrieved: set[str]) -> float:
    """Compute precision: fraction of retrieved items that are relevant."""
    if not retrieved:
        return 1.0
    hits = len(relevant & retrieved)
    return round(hits / len(retrieved), 6)


def f1_score(relevant: set[str], retrieved: set[str]) -> float:
    """Compute F1 score: harmonic mean of precision and recall."""
    p = precision(relevant, retrieved)
    r = recall(relevant, retrieved)
    if p + r == 0:
        return 0.0
    return round(2 * p * r / (p + r), 6)


def budget_adherence(used: int, budget: int) -> float:
    """Return 1.0 if within budget, 0.0 otherwise.

    Used tokens must be <= budget.  A small negative headroom (over-budget)
    returns 0.
    """
    return 1.0 if used <= budget else 0.0


def citation_validity(cited_ids: set[str], live_ids: set[str]) -> tuple[float, set[str]]:
    """Return (fraction_valid, invalid_ids).

    All cited ids should resolve to live (non-deleted) memories.
    """
    if not cited_ids:
        return 1.0, set()
    invalid = cited_ids - live_ids
    valid_count = len(cited_ids) - len(invalid)
    return round(valid_count / len(cited_ids), 6), invalid


def overdue_detection_accuracy(
    actual_overdue: set[str], detected_overdue: set[str]
) -> dict[str, float]:
    """Compute accuracy metrics for overdue detection."""
    return {
        "precision": precision(actual_overdue, detected_overdue),
        "recall": recall(actual_overdue, detected_overdue),
        "f1": f1_score(actual_overdue, detected_overdue),
    }


def stale_fact_avoidance(stale_facts: set[str], retrieved_facts: set[str]) -> float:
    """Fraction of retrieved facts that are NOT stale.

    Perfect score = 1.0 (no stale facts in results).
    """
    if not retrieved_facts:
        return 1.0
    fresh = retrieved_facts - stale_facts
    return round(len(fresh) / len(retrieved_facts), 6)


def as_of_accuracy(expected: dict[str, str], actual: dict[str, str]) -> float:
    """Fraction of fact keys with matching values in as-of queries."""
    if not expected:
        return 1.0
    correct = 0
    for k, v in expected.items():
        if k in actual and actual[k] == v:
            correct += 1
    return round(correct / len(expected), 6)


def replay_determinism_score(run_a_digest: str, run_b_digest: str) -> float:
    """Return 1.0 if two runs produce identical digests, 0.0 otherwise."""
    return 1.0 if run_a_digest == run_b_digest else 0.0


def deletion_resurrection_check(
    deleted_ids: set[str],
    query_results: dict[str, set[str]],
) -> tuple[bool, set[str]]:
    """Verify no deleted id appears in any query result.

    Returns (all_clean, resurrected_ids_found).
    """
    found: set[str] = set()
    for _query_name, result_ids in query_results.items():
        found |= result_ids & deleted_ids
    return len(found) == 0, found


def privacy_violation_count(violations: list[str]) -> int:
    """Count privacy violations; expected to be zero in clean runs."""
    return len(violations)


def coverage_score(
    required_items: set[str],
    covered_items: set[str],
) -> float:
    """Fraction of required items that are covered (e.g., in meeting prep)."""
    if not required_items:
        return 1.0
    return round(len(required_items & covered_items) / len(required_items), 6)


def aggregate_scorecards(cards: list[Scorecard]) -> Scorecard:
    """Aggregate multiple scenario scorecards into one summary.

    Takes the average of each metric across scenarios.
    """
    if not cards:
        return Scorecard(scenario="aggregate")

    metric_values: dict[str, list[float]] = {}
    metric_thresholds: dict[str, float | None] = {}
    metric_higher: dict[str, bool] = {}

    for card in cards:
        for m in card.metrics:
            if m.name not in metric_values:
                metric_values[m.name] = []
                metric_thresholds[m.name] = m.threshold
                metric_higher[m.name] = m.higher_is_better
            metric_values[m.name].append(m.value)

    agg = Scorecard(
        scenario="aggregate",
        details={"scenarios": [c.scenario for c in cards]},
    )
    for name, values in sorted(metric_values.items()):
        avg = round(sum(values) / len(values), 6)
        agg.add(
            MetricResult(
                name=name,
                value=avg,
                threshold=metric_thresholds[name],
                higher_is_better=metric_higher[name],
            )
        )
    return agg
