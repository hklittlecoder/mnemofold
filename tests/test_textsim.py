"""Tests for the shared bigram similarity primitive."""

from __future__ import annotations

import pytest

from mnemofold.textsim import (
    bigram_jaccard,
    char_bigrams,
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
