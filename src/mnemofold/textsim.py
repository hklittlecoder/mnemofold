"""Shared text-similarity primitives.

Folding (near-duplicate detection) and entity resolution (alias
matching) both rank candidates with character-bigram Jaccard
similarity. Keeping one implementation makes their thresholds
comparable and the behavior easy to test in isolation.
"""

from __future__ import annotations


def char_bigrams(text: str, *, fold_case: bool = False) -> set[str]:
    """Set of overlapping two-character grams of ``text``.

    Strings shorter than two characters have no bigrams and yield the
    empty set.
    """
    if fold_case:
        text = text.lower()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def bigram_jaccard(a: str, b: str, *, fold_case: bool = False) -> float:
    """Jaccard similarity of character bigrams, in [0.0, 1.0].

    Identical non-empty strings score 1.0; empty strings score 0.0.
    With ``fold_case=True`` the comparison is case-insensitive (folding
    uses this for prose); the default keeps case (name matching wants
    "ANA" and "Ana" to stay distinguishable candidates).
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    grams_a = char_bigrams(a, fold_case=fold_case)
    grams_b = char_bigrams(b, fold_case=fold_case)
    if not grams_a or not grams_b:
        return 0.0
    return len(grams_a & grams_b) / len(grams_a | grams_b)
