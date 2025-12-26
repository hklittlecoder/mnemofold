"""RetrievalEngine index export/import mirrors a freshly built index."""

import pytest

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import RetrievalEngine


def make_engine() -> RetrievalEngine:
    store = MemoryStore()
    store.add(
        MemoryItem(item_id="m1", tier=MemoryTier.SEMANTIC, title="t1", content="release notes")
    )
    store.add(
        MemoryItem(item_id="m2", tier=MemoryTier.SEMANTIC, title="t2", content="budget review")
    )
    engine = RetrievalEngine(store=store)
    engine.build_index()
    return engine


class TestEngineSnapshot:
    def test_export_import_preserves_search(self):
        engine = make_engine()
        snapshot = engine.export_index()
        fresh = RetrievalEngine(store=MemoryStore())
        fresh.import_index(snapshot)
        assert fresh.index.doc_count() == engine.index.doc_count()
        assert [i for i, _ in fresh.index.search("release")] == [
            i for i, _ in engine.index.search("release")
        ]

    def test_export_is_json_serializable_dict(self):
        snapshot = make_engine().export_index()
        assert set(snapshot) == {"k1", "b", "docs"}
        assert set(snapshot["docs"]) == {"m1", "m2"}

    def test_save_load_index_roundtrip(self, tmp_path):
        engine = make_engine()
        p = tmp_path / "engine_index.json"
        engine.save_index(p)
        fresh = RetrievalEngine(store=MemoryStore())
        fresh.load_index(p)
        assert fresh.export_index() == engine.export_index()

    def test_imported_index_scores_match_original(self):
        engine = make_engine()
        fresh = RetrievalEngine(store=MemoryStore())
        fresh.import_index(engine.export_index())
        original = engine.index.search("budget review")
        after = fresh.index.search("budget review")
        assert [i for i, _ in original] == [i for i, _ in after]
        assert [s for _, s in original] == pytest.approx([s for _, s in after])
