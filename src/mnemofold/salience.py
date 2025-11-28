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

    def percentile_ranks(self, items: list[SalienceFeatures]) -> list[float]:
        """Percentile rank of each item within the batch, in [0, 100].

        Highest-scoring item gets 100.0; lowest gets 0.0. Ties receive
        the same percentile (the highest rank among the tied group).
        Quantized to 6 decimals for deterministic output. An empty or
        single-item batch returns all 100.0.
        """
        if len(items) <= 1:
            return [100.0] * len(items)
        scores = self.score_batch(items)
        order = np.argsort(-scores)
        ranks = np.empty(len(items), dtype=np.float64)
        n = len(items)
        i = 0
        while i < n:
            j = i
            while j < n and scores[order[j]] == scores[order[i]]:
                j += 1
            percentile = 100.0 * (1.0 - i / max(1, n - 1))
            for k in range(i, j):
                ranks[order[k]] = round(percentile, 6)
            i = j
        return [round(float(r), 6) for r in ranks]

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


# --- Slice diagnostics ---------------------------------------------------------


@dataclass
class SalienceDiagnostics:
    """Transparent diagnostics over a batch of salience scores.

    Answers "why does this slice score the way it does" with plain NumPy
    statistics: distribution summaries, per-slice means, and Pearson
    correlations between each normalized feature and the final score.
    Every number is quantized to six decimals at this production point
    so reports are reproducible across platforms.
    """

    scorer: SalienceScorer

    def scores(self, batch: list[SalienceFeatures]) -> list[float]:
        return [round(self.scorer.score(features).score, 6) for features in batch]

    def describe(self, batch: list[SalienceFeatures]) -> dict[str, float]:
        """Count/mean/std/min/median/max of the batch scores."""
        if not batch:
            return {"count": 0.0, "mean": 0.0, "std": 0.0, "min": 0.0, "median": 0.0, "max": 0.0}
        scores = np.array(self.scores(batch), dtype=np.float64)
        return {
            "count": float(scores.size),
            "mean": round(float(scores.mean()), 6),
            "std": round(float(scores.std()), 6),
            "min": round(float(scores.min()), 6),
            "median": round(float(np.median(scores)), 6),
            "max": round(float(scores.max()), 6),
        }

    def slice_means(self, batch: list[SalienceFeatures], key: str) -> dict[str, float]:
        """Mean score per slice of one feature field.

        ``key`` must name a SalienceFeatures field; slice labels are the
        lowercase string forms of its values (``true``/``false`` for
        booleans). Output is sorted by slice label.
        """
        if not hasattr(SalienceFeatures(), key):
            raise ValueError(f"unknown feature field: {key}")
        buckets: dict[str, list[float]] = {}
        for features, score in zip(batch, self.scores(batch), strict=True):
            label = str(getattr(features, key)).lower()
            buckets.setdefault(label, []).append(score)
        return {
            label: round(float(np.mean(values)), 6) for label, values in sorted(buckets.items())
        }

    def feature_correlations(self, batch: list[SalienceFeatures]) -> dict[str, float]:
        """Pearson correlation of each normalized feature with the score.

        Constant features (zero variance) report 0.0 rather than NaN, so
        the output is always finite and comparable across batches.
        """
        zeros = {name: 0.0 for name in FEATURE_NAMES}
        if len(batch) < 2:
            return zeros
        matrix = np.array([self.scorer.feature_vector(f) for f in batch], dtype=np.float64)
        scores = np.array(self.scores(batch), dtype=np.float64)
        if float(scores.std()) == 0.0:
            return zeros
        out: dict[str, float] = {}
        for column, name in enumerate(FEATURE_NAMES):
            values = matrix[:, column]
            if float(values.std()) == 0.0:
                out[name] = 0.0
                continue
            correlation = float(np.corrcoef(values, scores)[0, 1])
            out[name] = round(correlation, 6)
        return out
