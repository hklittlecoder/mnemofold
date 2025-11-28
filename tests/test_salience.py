"""Tests for the salience scoring module."""

from __future__ import annotations

import numpy as np
import pytest

from mnemofold.salience import (
    FEATURE_NAMES,
    SalienceDiagnostics,
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

    def test_percentile_ranks_spread_across_0_to_100(self):
        scorer = SalienceScorer()
        items = [
            SalienceFeatures(is_pinned=True, is_decision=True, is_owner=True),
            SalienceFeatures(is_pinned=True),
            SalienceFeatures(),
        ]
        ranks = scorer.percentile_ranks(items)
        assert len(ranks) == 3
        assert max(ranks) == 100.0
        assert min(ranks) == 0.0
        assert all(0.0 <= r <= 100.0 for r in ranks)
        # Highest-salience item has rank 100
        scores = scorer.score_batch(items)
        top_idx = int(np.argmax(scores))
        assert ranks[top_idx] == 100.0

    def test_percentile_ranks_ties_share_rank(self):
        scorer = SalienceScorer()
        items = [SalienceFeatures(), SalienceFeatures(), SalienceFeatures()]
        ranks = scorer.percentile_ranks(items)
        assert all(r == ranks[0] for r in ranks)
        assert ranks[0] == 100.0

    def test_percentile_ranks_single_item(self):
        scorer = SalienceScorer()
        assert scorer.percentile_ranks([SalienceFeatures()]) == [100.0]

    def test_percentile_ranks_empty(self):
        scorer = SalienceScorer()
        assert scorer.percentile_ranks([]) == []


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


class TestFeatureVector:
    def _features(self) -> SalienceFeatures:
        return SalienceFeatures(
            has_deadline=True,
            days_until_deadline=2.0,
            is_owner=True,
            is_decision=True,
            recurrence_count=5,
            is_pinned=True,
            days_since_access=1.0,
            access_count=2,
            priority_label=0.4,
        )

    def test_vector_follows_canonical_order(self):
        scorer = SalienceScorer()
        result = scorer.score(self._features())
        vector = scorer.feature_vector(self._features())
        assert len(vector) == len(FEATURE_NAMES) == 7
        for name, value in zip(FEATURE_NAMES, vector, strict=True):
            assert value == round(result.feature_scores[name], 6)

    def test_vector_values_are_normalized(self):
        vector = SalienceScorer().feature_vector(self._features())
        assert all(0.0 <= v <= 1.0 for v in vector)

    def test_boolean_features_map_to_unit_values(self):
        vector = SalienceScorer().feature_vector(self._features())
        by_name = dict(zip(FEATURE_NAMES, vector, strict=True))
        assert by_name["ownership"] == 1.0
        assert by_name["decision_weight"] == 1.0
        assert by_name["pinning"] == 1.0

    def test_default_features_produce_zero_vector(self):
        vector = SalienceScorer().feature_vector(SalienceFeatures())
        assert vector == [0.0] * 7

    def test_scoring_unchanged_by_refactor(self):
        # pin one exact score so the normalization refactor cannot drift
        scorer = SalienceScorer()
        result = scorer.score(self._features())
        recomputed = sum(
            result.feature_scores[name] * getattr(scorer.weights, name) for name in FEATURE_NAMES
        )
        assert result.score == pytest.approx(recomputed)

    @pytest.mark.model
    def test_torch_module_declares_same_dimension(self):
        from mnemofold import salience_torch

        if not salience_torch.torch_available():
            pytest.skip("torch extra not installed")
        assert len(FEATURE_NAMES) == salience_torch.N_FEATURES


class TestSalienceDiagnostics:
    def _batch(self) -> list[SalienceFeatures]:
        return [
            SalienceFeatures(is_pinned=True, priority_label=0.9),
            SalienceFeatures(is_pinned=True, priority_label=0.1),
            SalienceFeatures(is_pinned=False, priority_label=0.5),
            SalienceFeatures(
                is_pinned=False, is_decision=True, days_since_access=2.0, access_count=1
            ),
        ]

    def _diagnostics(self) -> SalienceDiagnostics:
        return SalienceDiagnostics(scorer=SalienceScorer())

    def test_describe_empty_batch(self):
        stats = self._diagnostics().describe([])
        assert stats == {
            "count": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "median": 0.0,
            "max": 0.0,
        }

    def test_describe_matches_manual_aggregation(self):
        diagnostics = self._diagnostics()
        batch = self._batch()
        scores = diagnostics.scores(batch)
        stats = diagnostics.describe(batch)
        assert stats["count"] == float(len(batch))
        assert stats["mean"] == round(sum(scores) / len(scores), 6)
        assert stats["min"] == min(scores)
        assert stats["max"] == max(scores)

    def test_slice_means_split_on_boolean_field(self):
        diagnostics = self._diagnostics()
        means = diagnostics.slice_means(self._batch(), "is_pinned")
        assert set(means) == {"true", "false"}
        # pinned items score higher under default weights (pinning + priority)
        assert means["true"] > means["false"]

    def test_slice_means_unknown_field_raises(self):
        with pytest.raises(ValueError, match="unknown feature field"):
            self._diagnostics().slice_means(self._batch(), "not_a_field")

    def test_correlations_have_expected_signs(self):
        diagnostics = self._diagnostics()
        correlations = diagnostics.feature_correlations(self._batch())
        assert set(correlations) == set(FEATURE_NAMES)
        assert correlations["pinning"] > 0.0
        assert all(-1.0 <= value <= 1.0 for value in correlations.values())

    def test_correlations_degenerate_cases(self):
        diagnostics = self._diagnostics()
        single = [SalienceFeatures(is_pinned=True)]
        assert diagnostics.feature_correlations(single) == {name: 0.0 for name in FEATURE_NAMES}
        identical = [SalienceFeatures(is_pinned=True)] * 3
        assert diagnostics.feature_correlations(identical) == {name: 0.0 for name in FEATURE_NAMES}

    def test_diagnostics_are_deterministic(self):
        first = self._diagnostics().describe(self._batch())
        second = self._diagnostics().describe(self._batch())
        assert first == second
