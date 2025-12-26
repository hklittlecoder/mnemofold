"""End-to-end restart parity for a persisted BM25 index.

After save/load the reloaded index must return the same ranked ids, the
same scores (to float tolerance), and the same per-term explanations as
the original — otherwise a restart would silently change retrieval.
"""

import pytest

from mnemofold.retrieval import BM25Index


def make_index() -> BM25Index:
    idx = BM25Index()
    idx.add("d1", "release the kraken now")
    idx.add("d2", "release notes for march release")
    idx.add("d3", "quarterly budget review")
    idx.add("d4", "march madness bracket")
    return idx


QUERIES = ["release", "march release", "budget", "kraken now", "release notes"]


class TestRestartParity:
    def test_ranking_and_scores_survive_restart(self, tmp_path):
        idx = make_index()
        p = tmp_path / "idx.json"
        idx.save(p)
        reloaded = BM25Index.load(p)
        for q in QUERIES:
            original = idx.search(q, top_k=10)
            after = reloaded.search(q, top_k=10)
            assert [i for i, _ in original] == [i for i, _ in after], q
            assert [s for _, s in original] == pytest.approx([s for _, s in after]), q

    def test_explain_survives_restart(self, tmp_path):
        idx = make_index()
        p = tmp_path / "idx.json"
        idx.save(p)
        reloaded = BM25Index.load(p)
        for q in QUERIES:
            for doc_id, _ in idx.search(q, top_k=10):
                before = idx.explain(q, doc_id)
                after = reloaded.explain(q, doc_id)
                assert [(c.term, c.tf, c.df) for c in before] == [
                    (c.term, c.tf, c.df) for c in after
                ]
                assert [c.contribution for c in before] == pytest.approx(
                    [c.contribution for c in after]
                )

    def test_mutation_after_load_is_isolated(self, tmp_path):
        idx = make_index()
        p = tmp_path / "idx.json"
        idx.save(p)
        reloaded = BM25Index.load(p)
        reloaded.add("d5", "a completely new document about releases")
        assert reloaded.doc_count() == idx.doc_count() + 1
        assert idx.doc_count() == 4  # original untouched
