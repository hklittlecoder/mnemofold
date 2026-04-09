"""Shared text-similarity primitives.

Folding (near-duplicate detection) and entity resolution (alias
matching) both rank candidates with character-bigram Jaccard
similarity. Keeping one implementation makes their thresholds
comparable and the behavior easy to test in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


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


@dataclass(frozen=True)
class CandidateMatch:
    """One candidate scored against a query string."""

    candidate_id: str
    score: float
    text: str


def rank_candidates(
    query: str,
    candidates: dict[str, str],
    *,
    threshold: float = 0.0,
    top_k: int | None = None,
    fold_case: bool = False,
) -> list[CandidateMatch]:
    """Rank candidate texts by bigram Jaccard similarity to ``query``.

    ``candidates`` maps an id to its text. Returns matches above
    ``threshold`` (exclusive? — inclusive, so threshold=0 returns
    everything with any overlap), sorted by descending score with
    alphabetical tie-break on candidate_id for determinism.
    """
    matches: list[CandidateMatch] = []
    for cid, text in candidates.items():
        score = bigram_jaccard(query, text, fold_case=fold_case)
        if score >= threshold:
            matches.append(CandidateMatch(candidate_id=cid, score=score, text=text))
    matches.sort(key=lambda m: (-m.score, m.candidate_id))
    if top_k is not None:
        matches = matches[:top_k]
    return matches


def near_duplicate_clusters(
    items: dict[str, str],
    *,
    threshold: float,
    fold_case: bool = False,
) -> list[list[str]]:
    """Single-linkage clusters of items whose pairwise Jaccard >= threshold.

    Uses a union-find over pairs above ``threshold``. Order within each
    cluster and the order of clusters themselves are deterministic
    (sorted by the smallest id in each cluster, then alphabetically
    inside each cluster).

    Empty items are always placed in their own singleton cluster (they
    match nothing, including other empty items).
    """
    ids = sorted(items.keys())
    parent: dict[str, str] = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if not items[a] or not items[b]:
                continue
            score = bigram_jaccard(items[a], items[b], fold_case=fold_case)
            if score >= threshold:
                union(a, b)

    clusters_map: dict[str, list[str]] = {}
    for item_id in ids:
        root = find(item_id)
        clusters_map.setdefault(root, []).append(item_id)

    clusters = sorted(clusters_map.values(), key=lambda c: (c[0], len(c)))
    return [sorted(c) for c in clusters]


def tokenize_words(text: str, *, fold_case: bool = False) -> list[str]:
    """Word tokens split on non-alphanumeric runs, in original order.

    Mirrors the retrieval tokenizer's alphabet so similarity scores and
    search terms disagree about as little as possible. With
    ``fold_case=True`` tokens are lowercased.
    """
    if fold_case:
        text = text.lower()
    return _WORD_RE.findall(text)


def token_jaccard(a: str, b: str, *, fold_case: bool = False) -> float:
    """Jaccard similarity over word-token sets, in [0.0, 1.0].

    Unlike :func:`bigram_jaccard` this ignores word order entirely —
    "release the plan" and "the plan: release!" score 1.0 — which makes
    it the better signal for subject-line and title matching where
    punctuation and phrasing drift but vocabulary does not. Empty or
    token-less strings score 0.0.
    """
    if not a or not b:
        return 0.0
    tokens_a = set(tokenize_words(a, fold_case=fold_case))
    tokens_b = set(tokenize_words(b, fold_case=fold_case))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def combined_similarity(
    a: str,
    b: str,
    *,
    char_weight: float = 0.5,
    fold_case: bool = False,
) -> float:
    """Convex combination of character-bigram and word-token Jaccard.

    ``char_weight`` weights the bigram component; the token component
    gets ``1 - char_weight``. The endpoints reproduce the individual
    measures exactly (``char_weight=1.0`` is :func:`bigram_jaccard`,
    ``0.0`` is :func:`token_jaccard`), so callers can dial between
    order-sensitive and vocabulary-only similarity.
    """
    if not 0.0 <= char_weight <= 1.0:
        raise ValueError(f"char_weight must be in [0, 1], got {char_weight}")
    chars = bigram_jaccard(a, b, fold_case=fold_case)
    tokens = token_jaccard(a, b, fold_case=fold_case)
    return char_weight * chars + (1.0 - char_weight) * tokens
