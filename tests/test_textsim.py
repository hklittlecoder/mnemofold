"""Tests for the shared bigram similarity primitive."""

from __future__ import annotations

import pytest

from mnemofold.textsim import bigram_jaccard, char_bigrams


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
