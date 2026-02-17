"""Word-token similarity and the char/word combination dial."""

import pytest

from mnemofold.textsim import (
    bigram_jaccard,
    combined_similarity,
    token_jaccard,
    tokenize_words,
)


class TestTokenizeWords:
    def test_splits_on_non_alphanumerics(self):
        assert tokenize_words("release the plan!") == ["release", "the", "plan"]

    def test_keeps_underscores_and_digits(self):
        assert tokenize_words("v2_rollout 42") == ["v2_rollout", "42"]

    def test_fold_case(self):
        assert tokenize_words("Release PLAN", fold_case=True) == ["release", "plan"]
        assert tokenize_words("Release PLAN") == ["Release", "PLAN"]

    def test_empty_and_punctuation_only(self):
        assert tokenize_words("") == []
        assert tokenize_words("!!! ???") == []


class TestTokenJaccard:
    def test_word_order_does_not_matter(self):
        assert token_jaccard("release the plan", "plan the release") == 1.0
        # ... while the character-bigram view does see a difference
        assert bigram_jaccard("release the plan", "plan the release") < 1.0

    def test_punctuation_does_not_matter(self):
        assert token_jaccard("release the plan", "the plan: release!") == 1.0

    def test_partial_overlap(self):
        # {release, plan} vs {release, notes} -> 1/3
        assert token_jaccard("release plan", "release notes") == pytest.approx(1 / 3)

    def test_empty_strings_score_zero(self):
        assert token_jaccard("", "release") == 0.0
        assert token_jaccard("!!!", "release") == 0.0

    def test_fold_case_option(self):
        assert token_jaccard("Release", "release") == 0.0
        assert token_jaccard("Release", "release", fold_case=True) == 1.0

    def test_symmetry(self):
        a, b = "quarterly budget review", "budget review meeting"
        assert token_jaccard(a, b) == token_jaccard(b, a)


class TestCombinedSimilarity:
    def test_endpoints_reproduce_components(self):
        a, b = "release the plan", "plan the release"
        assert combined_similarity(a, b, char_weight=1.0) == bigram_jaccard(a, b)
        assert combined_similarity(a, b, char_weight=0.0) == token_jaccard(a, b)

    def test_midpoint_is_the_mean(self):
        a, b = "release notes", "release notes v2"
        expected = 0.5 * bigram_jaccard(a, b) + 0.5 * token_jaccard(a, b)
        assert combined_similarity(a, b) == pytest.approx(expected)

    def test_invalid_weight_rejected(self):
        for bad in (-0.1, 1.5):
            with pytest.raises(ValueError, match="char_weight"):
                combined_similarity("a", "b", char_weight=bad)

    def test_identical_strings_score_one(self):
        assert combined_similarity("same text", "same text") == 1.0

    def test_fold_case_passed_through(self):
        assert combined_similarity("Release", "release", char_weight=0.0) == 0.0
        assert combined_similarity("Release", "release", char_weight=0.0, fold_case=True) == 1.0
