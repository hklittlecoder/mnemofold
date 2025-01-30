"""Tests for the salience scoring module."""

from __future__ import annotations

import numpy as np
import pytest

from mnemofold.salience import (
    SalienceFeatures,
    SalienceScorer,
    SalienceWeights,
    compute_deadline_proximity,
)


class TestSalienceFeatures:
    def test_defaults(self):
        f = SalienceFeatures()
        assert f.has_deadline is False
        assert f.is_owner is False
        assert f.is_pinned is False
        assert f.salience if hasattr(f, "salience") else True  # no .salience attr


class TestSalienceWeights:
    def test_default_weights_positive(self):
        w = SalienceWeights()
        total = (
            w.deadline_proximity
            + w.ownership
            + w.decision_weight
            + w.recurrence
            + w.pinning
            + w.recency
            + w.priority
        )
        assert total > 0

    def test_zero_weights_raises(self):
        w = SalienceWeights(
            deadline_proximity=0,
            ownership=0,
            decision_weight=0,
            recurrence=0,
            pinning=0,
            recency=0,
            priority=0,
        )
        with pytest.raises(ValueError, match="weights must sum"):
            SalienceScorer(w)


class TestSalienceScorer:
    def test_score_in_range(self):
        scorer = SalienceScorer()
        f = SalienceFeatures(is_owner=True, is_pinned=True, days_since_access=1.0, access_count=5)
        result = scorer.score(f)
        assert 0.0 <= result.score <= 1.0

    def test_pinned_increases_score(self):
        scorer = SalienceScorer()
        base = SalienceFeatures()
        pinned = SalienceFeatures(is_pinned=True)
        assert scorer.score(pinned).score > scorer.score(base).score

    def test_owner_increases_score(self):
        scorer = SalienceScorer()
        base = SalienceFeatures()
        owner = SalienceFeatures(is_owner=True)
        assert scorer.score(owner).score > scorer.score(base).score

    def test_decision_increases_score(self):
        scorer = SalienceScorer()
        base = SalienceFeatures()
        decision = SalienceFeatures(is_decision=True)
        assert scorer.score(decision).score > scorer.score(base).score

    def test_deadline_urgent_has_high_score(self):
        scorer = SalienceScorer()
        soon = SalienceFeatures(has_deadline=True, days_until_deadline=1.0)
        far = SalienceFeatures(has_deadline=True, days_until_deadline=30.0)
        assert scorer.score(soon).score > scorer.score(far).score

    def test_overdue_deadline_max_score(self):
        scorer = SalienceScorer()
        overdue = SalienceFeatures(has_deadline=True, days_until_deadline=-5.0)
        result = scorer.score(overdue)
        # Deadline proximity should be 1.0
        assert result.feature_scores["deadline_proximity"] == 1.0

    def test_no_deadline_zero_contribution(self):
        scorer = SalienceScorer()
        f = SalienceFeatures(has_deadline=False)
        result = scorer.score(f)
        assert result.feature_scores["deadline_proximity"] == 0.0

    def test_recency_decreases_with_time(self):
        scorer = SalienceScorer()
        recent = SalienceFeatures(days_since_access=1.0, access_count=3)
        old = SalienceFeatures(days_since_access=30.0, access_count=3)
        assert scorer.score(recent).score > scorer.score(old).score

    def test_never_accessed_zero_recency(self):
        scorer = SalienceScorer()
        f = SalienceFeatures(days_since_access=0.0, access_count=0)
        result = scorer.score(f)
        assert result.feature_scores["recency"] == 0.0

    def test_recurrence_saturates(self):
        scorer = SalienceScorer()
        f5 = SalienceFeatures(recurrence_count=5)
        f50 = SalienceFeatures(recurrence_count=50)
        # Both should be near 1.0 (saturated)
        s5 = scorer.score(f5).feature_scores["recurrence"]
        s50 = scorer.score(f50).feature_scores["recurrence"]
        assert s50 <= 1.0
        assert s50 >= s5

    def test_top_features_sorted(self):
        scorer = SalienceScorer()
        f = SalienceFeatures(
            is_pinned=True, is_owner=True, has_deadline=True, days_until_deadline=1.0
        )
        result = scorer.score(f)
        top = result.top_features
        assert top[0][1] >= top[-1][1]

    def test_score_batch(self):
        scorer = SalienceScorer()
        items = [
            SalienceFeatures(is_owner=True),
            SalienceFeatures(is_pinned=True),
            SalienceFeatures(),
        ]
        scores = scorer.score_batch(items)
        assert len(scores) == 3
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_rank(self):
        scorer = SalienceScorer()
        items = [
            SalienceFeatures(is_pinned=True),  # high
            SalienceFeatures(),  # low
            SalienceFeatures(is_owner=True, is_pinned=True),  # highest
        ]
        ranks = scorer.rank(items)
        # Highest score first
        assert ranks[0] == 2
        assert ranks[-1] == 1

    def test_empty_batch(self):
        scorer = SalienceScorer()
        scores = scorer.score_batch([])
        assert len(scores) == 0
        assert isinstance(scores, np.ndarray)


class TestDeadlineProximity:
    def test_future_deadline(self):
        has_d, days = compute_deadline_proximity(
            "2024-01-15T00:00:00+00:00", "2024-01-10T00:00:00+00:00"
        )
        assert has_d is True
        assert days == pytest.approx(5.0)

    def test_overdue_deadline(self):
        has_d, days = compute_deadline_proximity(
            "2024-01-10T00:00:00+00:00", "2024-01-15T00:00:00+00:00"
        )
        assert has_d is True
        assert days == pytest.approx(-5.0)

    def test_invalid_format(self):
        has_d, days = compute_deadline_proximity("not-a-date", "2024-01-01T00:00:00+00:00")
        assert has_d is False
        assert days == 0.0
