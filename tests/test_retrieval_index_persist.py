"""BM25 index serialization: rebuild fidelity and version guarding."""

import pytest

from mnemofold.persist import PersistError
from mnemofold.retrieval import BM25Index


def make_index() -> BM25Index:
    idx = BM25Index()
    idx.add("d1", "release the kraken")
    idx.add("d2", "release notes for march")
    idx.add("d3", "quarterly budget review")
    return idx


class TestIndexSerde:
    def test_empty_index_golden_bytes(self, tmp_path):
        p = tmp_path / "empty.json"
        BM25Index().save(p)
        assert (
            p.read_text(encoding="utf-8")
            == '{"payload":{"b":0.75,"docs":{},"k1":1.5},"schema":"bm25_index","schema_version":1}'
        )

    def test_to_dict_is_sorted_and_complete(self):
        d = make_index().to_dict()
        assert list(d["docs"]) == ["d1", "d2", "d3"]
        assert d["k1"] == 1.5 and d["b"] == 0.75

    def test_from_dict_rebuilds_identical_search(self):
        idx = make_index()
        rebuilt = BM25Index.from_dict(idx.to_dict())
        assert rebuilt.ids() == idx.ids()
        assert rebuilt.doc_count() == idx.doc_count()
        for q in ("release", "budget review", "notes"):
            original, after = idx.search(q), rebuilt.search(q)
            assert [i for i, _ in original] == [i for i, _ in after]
            assert [s for _, s in original] == pytest.approx([s for _, s in after])

    def test_rebuild_is_insertion_order_independent(self):
        a = BM25Index()
        a.add("d1", "alpha beta")
        a.add("d2", "beta gamma")
        b = BM25Index()
        b.add("d2", "beta gamma")
        b.add("d1", "alpha beta")
        assert a.to_dict() == b.to_dict()
        sa = BM25Index.from_dict(a.to_dict()).search("beta")
        sb = BM25Index.from_dict(b.to_dict()).search("beta")
        assert [i for i, _ in sa] == [i for i, _ in sb]
        assert [s for _, s in sa] == pytest.approx([s for _, s in sb])

    def test_params_are_preserved(self):
        idx = BM25Index(k1=2.0, b=0.5)
        idx.add("d1", "alpha")
        rebuilt = BM25Index.from_dict(idx.to_dict())
        assert rebuilt.k1 == 2.0 and rebuilt.b == 0.5

    def test_file_roundtrip(self, tmp_path):
        p = tmp_path / "idx.json"
        idx = make_index()
        idx.save(p)
        loaded = BM25Index.load(p)
        assert loaded.to_dict() == idx.to_dict()

    def test_load_rejects_foreign_schema(self, tmp_path):
        from mnemofold.persist import write_envelope

        p = tmp_path / "bad.json"
        write_envelope(p, "not_an_index", {"docs": {}})
        with pytest.raises(PersistError, match="schema mismatch"):
            BM25Index.load(p)
