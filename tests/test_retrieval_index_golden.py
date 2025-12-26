"""Golden fixture for the serialized BM25 index payload.

The index snapshot is byte-compared so ranking parameters and document
ordering cannot drift unnoticed; a second build must reproduce the same
bytes from the same logical corpus.
"""

from pathlib import Path

from mnemofold.retrieval import BM25Index

FIXTURE = Path(__file__).parent / "fixtures" / "bm25_index_golden.json"


def _corpus() -> BM25Index:
    idx = BM25Index()
    idx.add("d3", "alpha gamma delta")
    idx.add("d1", "alpha beta")
    idx.add("d2", "beta gamma")
    return idx


def test_save_matches_golden_bytes(tmp_path):
    p = tmp_path / "idx.json"
    _corpus().save(p)
    assert p.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")


def test_golden_loads_and_searches(tmp_path):
    loaded = BM25Index.load(FIXTURE)
    assert loaded.ids() == ["d1", "d2", "d3"]
    top = loaded.search("alpha", top_k=1)
    assert top[0][0] in {"d1", "d3"}


def test_regeneration_is_stable(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _corpus().save(a)
    _corpus().save(b)
    assert a.read_bytes() == b.read_bytes() == FIXTURE.read_bytes()
