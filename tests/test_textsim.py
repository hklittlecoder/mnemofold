"""Tests for the shared bigram similarity primitive."""

from __future__ import annotations

import pytest

from mnemofold.textsim import (
    bigram_jaccard,
    char_bigrams,
    near_duplicate_clusters,
    rank_candidates,
)


class TestCharBigrams:
    def test_overlapping_pairs(self):
        assert char_bigrams("abc") == {"ab", "bc"}

    def test_case_folding_is_optional(self):
        assert char_bigrams("AB", fold_case=True) == {"ab"}
        assert char_bigrams("AB") == {"AB"}

    def test_short_and_empty_strings_have_no_bigrams(self):
        assert char_bigrams("") == set()
        assert char_bigrams("a") == set()


class TestBigramJaccard:
    def test_identical_strings_score_one(self):
        assert bigram_jaccard("release plan", "release plan") == 1.0

    def test_empty_or_tiny_strings_score_zero(self):
        assert bigram_jaccard("", "abc") == 0.0
        assert bigram_jaccard("a", "a") == 1.0  # identical early-return
        assert bigram_jaccard("a", "b") == 0.0

    def test_disjoint_strings_score_zero(self):
        assert bigram_jaccard("alpha beta", "zzz yyy") == 0.0

    def test_case_sensitivity_by_default(self):
        assert bigram_jaccard("ABC", "abc") == 0.0
        assert bigram_jaccard("ABC", "abc", fold_case=True) == 1.0

    def test_partial_overlap_lands_between_zero_and_one(self):
        score = bigram_jaccard("release plan", "release plans")
        assert 0.0 < score < 1.0

    @pytest.mark.parametrize("text", ["alpha", "a longer sentence with words"])
    def test_symmetry(self, text):
        other = "beta variant"
        assert bigram_jaccard(text, other) == bigram_jaccard(other, text)


class TestRankCandidates:
    def test_ranks_by_descending_score(self):
        candidates = {
            "a": "release plan",
            "b": "release plans",
            "c": "unrelated thing",
        }
        ranked = rank_candidates("release plan", candidates)
        assert ranked[0].candidate_id == "a"
        assert ranked[0].score == 1.0
        assert ranked[-1].score <= ranked[0].score

    def test_threshold_filters_low_scores(self):
        candidates = {"a": "hello world", "b": "xyz"}
        ranked = rank_candidates("hello world", candidates, threshold=0.9)
        assert all(m.score >= 0.9 for m in ranked)
        assert len(ranked) == 1

    def test_top_k_limits_results(self):
        candidates = {f"c{i}": f"target phrase {i}" for i in range(10)}
        ranked = rank_candidates("target phrase 0", candidates, top_k=3)
        assert len(ranked) == 3

    def test_tie_break_is_alphabetical_by_id(self):
        candidates = {"b": "abc", "a": "abc"}
        ranked = rank_candidates("abc", candidates)
        assert ranked[0].candidate_id == "a"
        assert ranked[1].candidate_id == "b"
        assert ranked[0].score == ranked[1].score

    def test_empty_candidates_returns_empty(self):
        assert rank_candidates("q", {}) == []

    def test_fold_case_option_passed_through(self):
        candidates = {"upper": "HELLO", "lower": "hello"}
        folded = rank_candidates("hello", candidates, fold_case=True)
        assert folded[0].score == 1.0
        assert len([m for m in folded if m.score == 1.0]) == 2


class TestNearDuplicateClusters:
    def test_identical_items_cluster_together(self):
        items = {"a": "release plan", "b": "release plan", "c": "unrelated"}
        clusters = near_duplicate_clusters(items, threshold=0.9)
        # two clusters: [a, b] and [c]
        assert len(clusters) == 2
        assert {"a", "b"} in [set(c) for c in clusters]
        assert ["c"] in clusters

    def test_single_linkage_chain(self):
        # a is close to b, b is close to c, a is far from c
        items = {
            "a": "release plan v1",
            "b": "release plan v2",
            "c": "release plan v3",
        }
        clusters = near_duplicate_clusters(items, threshold=0.6)
        # all three should end up in one cluster via single linkage
        assert len(clusters) == 1
        assert set(clusters[0]) == {"a", "b", "c"}

    def test_empty_items_are_singletons(self):
        items = {"a": "", "b": "", "c": "hello"}
        clusters = near_duplicate_clusters(items, threshold=0.0)
        # empty strings never match anything, each is its own cluster
        assert len(clusters) == 3

    def test_threshold_controls_cluster_size(self):
        items = {"a": "hello world", "b": "hello worlds", "c": "goodbye"}
        clusters = near_duplicate_clusters(items, threshold=0.95)
        assert len(clusters) == 3  # all separate above the 0.909 a/b score
        clusters_low = near_duplicate_clusters(items, threshold=0.3)
        assert len(clusters_low) <= 2  # a and b merge at low threshold

    def test_empty_input(self):
        assert near_duplicate_clusters({}, threshold=0.5) == []

    def test_cluster_order_is_deterministic(self):
        items = {"z": "aaa", "a": "aaa", "m": "bbb"}
        clusters = near_duplicate_clusters(items, threshold=0.9)
        # clusters ordered by smallest id
        assert clusters[0][0] == "a"
        assert clusters[-1][0] == "m"
        # each cluster internally sorted
        for c in clusters:
            assert c == sorted(c)
