"""Randomized explain/search parity: the breakdown never drifts from ranking.

Corpora and queries are generated from seeded RNGs over a small vocab,
so every run replays identically while covering far more term/document
shape combinations than hand-written fixtures.
"""

import random

from mnemofold.retrieval import BM25Index

VOCAB = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "release",
    "notes",
    "budget",
    "plan",
    "review",
    "deploy",
]


def random_index(seed: int) -> tuple[BM25Index, random.Random]:
    rng = random.Random(seed)
    idx = BM25Index()
    for i in range(rng.randint(2, 8)):
        tokens = [rng.choice(VOCAB) for _ in range(rng.randint(1, 12))]
        idx.add(f"d{i}", " ".join(tokens))
    return idx, rng


class TestExplainSearchParity:
    def test_parity_holds_across_seeds(self):
        for seed in range(25):
            idx, rng = random_index(seed)
            for _ in range(5):
                q = " ".join(rng.choice(VOCAB) for _ in range(rng.randint(1, 4)))
                for doc_id, score in idx.search(q, top_k=50):
                    parts = idx.explain(q, doc_id)
                    assert parts, (seed, q, doc_id)
                    total = sum(c.contribution for c in parts)
                    assert abs(total - score) < 1e-9, (seed, q, doc_id)

    def test_docs_outside_results_explain_to_zero_or_empty(self):
        for seed in range(10):
            idx, rng = random_index(seed)
            q = " ".join(rng.choice(VOCAB) for _ in range(2))
            hit_ids = {doc_id for doc_id, _ in idx.search(q, top_k=50)}
            for doc_id in idx.ids():
                if doc_id in hit_ids:
                    continue
                total = sum(c.contribution for c in idx.explain(q, doc_id))
                assert total == 0.0, (seed, q, doc_id)

    def test_contributions_are_non_negative(self):
        for seed in range(10):
            idx, rng = random_index(seed)
            q = " ".join(rng.choice(VOCAB) for _ in range(3))
            for doc_id in idx.ids():
                for part in idx.explain(q, doc_id):
                    assert part.contribution >= 0.0
                    assert part.idf >= 0.0
                    assert part.tf >= 1
                    assert part.df >= 1
