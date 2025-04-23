"""Salience scoring: transparent NumPy-based feature computation.

Salience measures how important or relevant a memory item is. Features
include deadline proximity, ownership, decision weight, recurrence,
explicit pinning, and recency. The score is a weighted combination of
normalized features.

An optional PyTorch MLP provides a learned rank-fusion baseline; all
torch-dependent code is in a separate module and guarded by import checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

# Canonical feature ordering — the single source of truth shared by the
# NumPy scorer and the optional torch MLP so both see identical inputs.
FEATURE_NAMES: tuple[str, ...] = (
    "deadline_proximity",
    "ownership",
    "decision_weight",
    "recurrence",
    "pinning",
    "recency",
    "priority",
)


@dataclass
class SalienceFeatures:
    """Input features for salience computation.

    All features are normalized to [0, 1] range by the scorer.
    """

    has_deadline: bool = False
    days_until_deadline: float = 0.0
    is_owner: bool = False
    is_decision: bool = False
    recurrence_count: int = 0
    is_pinned: bool = False
    days_since_access: float = 0.0
    access_count: int = 0
    priority_label: float = 0.0  # user-assigned priority [0,1]


@dataclass
class SalienceWeights:
    """Weights for each feature in the linear salience score."""

    deadline_proximity: float = 0.25
    ownership: float = 0.15
    decision_weight: float = 0.20
    recurrence: float = 0.10
    pinning: float = 0.15
    recency: float = 0.10
    priority: float = 0.05


@dataclass
class SalienceResult:
    """Result of salience computation."""

    score: float
    feature_scores: dict[str, float]
    weighted_scores: dict[str, float]

    @property
    def top_features(self) -> list[tuple[str, float]]:
        """Return features sorted by weighted contribution (descending)."""
        return sorted(self.weighted_scores.items(), key=lambda x: x[1], reverse=True)


class SalienceScorer:
    """Computes salience scores using weighted feature combination.

    The score is a weighted sum of normalized feature values, each in
    [0, 1]. Final score is always in [0, 1].
    """

    def __init__(self, weights: SalienceWeights | None = None) -> None:
        self.weights = weights or SalienceWeights()
        self._validate_weights()

    def _validate_weights(self) -> None:
        total = (
            self.weights.deadline_proximity
            + self.weights.ownership
            + self.weights.decision_weight
            + self.weights.recurrence
            + self.weights.pinning
            + self.weights.recency
            + self.weights.priority
        )
        if total <= 0:
            raise ValueError("salience weights must sum to a positive value")
        self._weight_sum = total

    def score(self, features: SalienceFeatures) -> SalienceResult:
        """Compute salience score for a single item."""
        feature_scores = self._normalized(features)
        weighted = {
            name: feature_scores[name] * getattr(self.weights, name) for name in FEATURE_NAMES
        }

        total = sum(weighted.values()) / self._weight_sum
        total = max(0.0, min(1.0, total))

        return SalienceResult(score=total, feature_scores=feature_scores, weighted_scores=weighted)

    def feature_vector(self, features: SalienceFeatures) -> list[float]:
        """Normalized features in canonical FEATURE_NAMES order.

        Quantized at this production point so vectors, digests, and any
        downstream learned model see identical values across platforms.
        """
        normalized = self._normalized(features)
        return [round(normalized[name], 6) for name in FEATURE_NAMES]

    def _normalized(self, features: SalienceFeatures) -> dict[str, float]:
        """Normalize every raw feature into [0, 1], keyed by FEATURE_NAMES."""
        return {
            "deadline_proximity": self._norm_deadline(features),
            "ownership": 1.0 if features.is_owner else 0.0,
            "decision_weight": 1.0 if features.is_decision else 0.0,
            "recurrence": min(1.0, features.recurrence_count / 10.0),
            "pinning": 1.0 if features.is_pinned else 0.0,
            "recency": self._norm_recency(features),
            "priority": max(0.0, min(1.0, features.priority_label)),
        }

    def score_batch(self, items: list[SalienceFeatures]) -> np.ndarray:
        """Compute salience scores for a batch of items.

        Returns a numpy array of scores in [0, 1].
        """
        if not items:
            return np.array([], dtype=np.float64)
        scores = [self.score(f).score for f in items]
        return np.array(scores, dtype=np.float64)

    def rank(self, items: list[SalienceFeatures]) -> list[int]:
        """Return indices of items sorted by salience (highest first)."""
        scores = self.score_batch(items)
        return list(np.argsort(-scores))

    def _norm_deadline(self, f: SalienceFeatures) -> float:
        """Normalize deadline proximity: closer deadline = higher score.

        No deadline -> 0. Past deadline -> 1.0 (most urgent).
        30+ days away -> ~0. Scale exponentially.
        """
        if not f.has_deadline:
            return 0.0
        if f.days_until_deadline <= 0:
            return 1.0
        # Exponential decay: 1.0 at 0 days, ~0.05 at 30 days
        return float(np.exp(-f.days_until_deadline / 7.0))

    def _norm_recency(self, f: SalienceFeatures) -> float:
        """Normalize recency: more recently accessed = higher score.

        Never accessed -> 0. Accessed today -> 1.0.
        """
        if f.days_since_access <= 0:
            return 1.0 if f.access_count > 0 else 0.0
        return float(np.exp(-f.days_since_access / 14.0))


def compute_deadline_proximity(due_date: str, now: str) -> tuple[bool, float]:
    """Compute (has_deadline, days_until_deadline) from date strings.

    Returns (False, 0.0) if parsing fails.
    """
    try:
        t_due = datetime.fromisoformat(due_date)
        t_now = datetime.fromisoformat(now)
    except (ValueError, TypeError):
        return False, 0.0
    if t_due.tzinfo is None:
        t_due = t_due.replace(tzinfo=UTC)
    if t_now.tzinfo is None:
        t_now = t_now.replace(tzinfo=UTC)
    days = (t_due - t_now).total_seconds() / 86400.0
    return True, days
