"""Per-term BM25 explanations must agree with search scores."""

import math

import pytest

from mnemofold.retrieval import BM25Index


def make_index() -> BM25Index:
    idx = BM25Index()
    idx.add("d1", "release the kraken")
    idx.add("d2", "release notes for march")
    idx.add("d3", "quarterly budget review")
    return idx


class TestExplain:
    def test_contributions_sum_to_search_score(self):
        idx = make_index()
        scores = dict(idx.search("release notes"))
        assert scores
        for doc_id, score in scores.items():
            total = sum(c.contribution for c in idx.explain("release notes", doc_id))
            assert total == pytest.approx(score, abs=1e-9)

    def test_unknown_item_returns_empty(self):
        assert make_index().explain("release", "ghost") == []

    def test_empty_query_returns_empty(self):
        assert make_index().explain("", "d1") == []
        assert make_index().explain("   ", "d1") == []

    def test_terms_missing_from_the_doc_are_skipped(self):
        idx = make_index()
        assert idx.explain("budget", "d1") == []
        parts = idx.explain("release budget", "d1")
        assert [p.term for p in parts] == ["release"]

    def test_unknown_corpus_terms_are_skipped(self):
        assert make_index().explain("zebra release", "d1") == [
            make_index().explain("release", "d1")[0]
        ]

    def test_duplicate_query_terms_mirror_search_double_counting(self):
        idx = make_index()
        single = dict(idx.search("release"))
        double = dict(idx.search("release release"))
        for doc_id in single:
            assert double[doc_id] == pytest.approx(single[doc_id] * 2, abs=1e-9)
            parts = idx.explain("release release", doc_id)
            assert len(parts) == 2
            total = sum(p.contribution for p in parts)
            assert total == pytest.approx(double[doc_id], abs=1e-9)

    def test_order_is_contribution_desc_then_term(self):
        idx = make_index()
        parts = idx.explain("release notes for", "d2")
        keys = [(-p.contribution, p.term) for p in parts]
        assert keys == sorted(keys)

    def test_idf_matches_the_bm25_formula(self):
        idx = make_index()
        parts = {p.term: p for p in idx.explain("release budget", "d1")}
        # "release" appears in 2 of 3 docs
        assert parts["release"].df == 2
        assert parts["release"].idf == pytest.approx(math.log(1 + (3 - 2 + 0.5) / (2 + 0.5)))
        assert parts["release"].tf == 1

    def test_explain_after_remove_stays_consistent(self):
        idx = make_index()
        idx.remove("d2")
        scores = dict(idx.search("release notes"))
        for doc_id, score in scores.items():
            total = sum(c.contribution for c in idx.explain("release notes", doc_id))
            assert total == pytest.approx(score, abs=1e-9)
