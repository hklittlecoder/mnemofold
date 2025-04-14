"""Tests for retrieval module."""

from __future__ import annotations

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import (
    BM25Index,
    ParsedQuery,
    RetrievalEngine,
    mmr_rerank,
    parse_query,
    tokenize,
)


class TestTokenizer:
    def test_basic(self):
        assert "hello" in tokenize("Hello, World!")
        assert "world" in tokenize("Hello, World!")

    def test_lowercase(self):
        tokens = tokenize("Foo BAR")
        assert tokens == ["foo", "bar"]

    def test_empty(self):
        assert tokenize("") == []


class TestBM25Index:
    def test_add_and_search(self):
        idx = BM25Index()
        idx.add("d1", "the quick brown fox jumps over the lazy dog")
        idx.add("d2", "a quick brown cat")
        idx.add("d3", "the lazy dog sleeps")
        results = idx.search("quick brown", top_k=10)
        assert len(results) >= 2
        # d1 and d2 both have quick+brown
        ids = [r[0] for r in results]
        assert "d1" in ids
        assert "d2" in ids

    def test_search_no_match(self):
        idx = BM25Index()
        idx.add("d1", "hello world")
        results = idx.search("xyzzy")
        assert results == []

    def test_remove(self):
        idx = BM25Index()
        idx.add("d1", "hello world")
        idx.remove("d1")
        assert idx.doc_count() == 0
        results = idx.search("hello")
        assert results == []

    def test_empty_query(self):
        idx = BM25Index()
        idx.add("d1", "test")
        assert idx.search("") == []

    def test_doc_count(self):
        idx = BM25Index()
        assert idx.doc_count() == 0
        idx.add("d1", "a")
        assert idx.doc_count() == 1
        idx.add("d2", "b")
        assert idx.doc_count() == 2

    def test_results_ranked_by_score(self):
        idx = BM25Index()
        idx.add("d1", "apple apple apple banana")
        idx.add("d2", "banana cherry")
        results = idx.search("apple")
        assert len(results) == 1
        assert results[0][0] == "d1"


class TestMMRRerank:
    def test_mmr_promotes_diversity(self):
        results = [
            ("a", 1.0),
            ("b", 0.9),
            ("c", 0.8),
        ]
        texts = {
            "a": "machine learning neural network deep",
            "b": "machine learning neural network deep",  # very similar to a
            "c": "cooking recipe food kitchen",  # very different
        }
        # With lambda=0.5, MMR should pick a (highest score), then c (diverse), then b
        ranked = mmr_rerank(results, texts, lambda_param=0.5, top_k=3)
        assert ranked[0] == "a"
        assert len(ranked) == 3

    def test_mmr_high_lambda_more_relevance(self):
        results = [("a", 1.0), ("b", 0.9), ("c", 0.8)]
        texts = {"a": "x y z", "b": "a b c", "c": "p q r"}
        # All dissimilar, high lambda → relevance order
        ranked = mmr_rerank(results, texts, lambda_param=0.9, top_k=3)
        assert ranked == ["a", "b", "c"]

    def test_mmr_empty(self):
        assert mmr_rerank([], {}, top_k=10) == []

    def test_mmr_top_k(self):
        results = [("a", 1.0), ("b", 0.9), ("c", 0.8)]
        texts = {"a": "x", "b": "y", "c": "z"}
        ranked = mmr_rerank(results, texts, top_k=2)
        assert len(ranked) == 2


class TestRetrievalEngine:
    def test_basic_search(self):
        store = MemoryStore()
        for i in range(5):
            item = MemoryItem(
                f"item_{i}",
                MemoryTier.SEMANTIC,
                f"This is document number {i} about topic {i % 3}",
                title=f"Doc {i}",
            )
            store.add(item)
        engine = RetrievalEngine(store)
        engine.build_index()
        results = engine.search("document", top_k=3)
        assert len(results) == 3
        assert all(r.item_id for r in results)

    def test_citations_resolve(self):
        store = MemoryStore()
        for i in range(5):
            item = MemoryItem(f"i{i}", MemoryTier.SEMANTIC, f"content {i}", title=f"t{i}")
            store.add(item)
        engine = RetrievalEngine(store)
        engine.build_index()
        assert engine.property_citations_resolve("content")

    def test_search_with_tag_filter(self):
        store = MemoryStore()
        a = MemoryItem("a", MemoryTier.SEMANTIC, "about python code", title="A", tags={"dev"})
        b = MemoryItem("b", MemoryTier.SEMANTIC, "about cooking", title="B", tags={"food"})
        store.add(a)
        store.add(b)
        engine = RetrievalEngine(store)
        engine.build_index()
        results = engine.search("about", tags={"dev"})
        assert len(results) == 1
        assert results[0].item_id == "a"

    def test_empty_results_for_nonexistent_terms(self):
        store = MemoryStore()
        item = MemoryItem("a", MemoryTier.SEMANTIC, "hello world", title="Hi")
        store.add(item)
        engine = RetrievalEngine(store)
        engine.build_index()
        results = engine.search("xyzzynonexistent")
        assert len(results) == 0


class TestQueryParser:
    def test_plain_text_query(self):
        parsed = parse_query("budget planning notes")
        assert parsed.text == "budget planning notes"
        assert not parsed.has_filters()

    def test_filters_extracted_from_any_position(self):
        parsed = parse_query("person:alice budget tag:finance before:2025-03-01")
        assert parsed.text == "budget"
        assert parsed.people == ["alice"]
        assert parsed.tags == ["finance"]
        assert parsed.before == "2025-03-01"

    def test_filter_keys_are_case_insensitive(self):
        parsed = parse_query("Tag:Finance PERSON:Bob")
        assert parsed.tags == ["finance"]
        assert parsed.people == ["bob"]
        assert parsed.text == ""

    def test_list_filters_accumulate_without_duplicates(self):
        parsed = parse_query("tag:a tag:b tag:a project:alpha person:carol")
        assert parsed.tags == ["a", "b"]
        assert parsed.projects == ["alpha"]
        assert parsed.people == ["carol"]

    def test_instant_filters_last_wins(self):
        parsed = parse_query("before:2025-01-01 before:2025-06-01")
        assert parsed.before == "2025-06-01"

    def test_on_after_before_combine(self):
        parsed = parse_query("on:2025-03-01 after:2025-01-01 standup")
        assert parsed.on == "2025-03-01"
        assert parsed.after == "2025-01-01"
        assert parsed.text == "standup"

    def test_words_with_colons_stay_in_text(self):
        parsed = parse_query("see taglike:x and mytag:y notes")
        assert parsed.tags == []
        assert "taglike:x" in parsed.text
        assert "mytag:y" in parsed.text

    def test_whitespace_collapses_in_text(self):
        parsed = parse_query("  alpha   tag:x    beta  ")
        assert parsed.text == "alpha beta"

    def test_dict_roundtrip(self):
        parsed = parse_query("budget person:alice tag:finance after:2025-01-01")
        assert ParsedQuery.from_dict(parsed.to_dict()) == parsed

    def test_empty_query(self):
        parsed = parse_query("")
        assert parsed.text == ""
        assert not parsed.has_filters()


class TestParsedSearch:
    def _item(self, item_id, content, *, created="", tags=None, metadata=None) -> MemoryItem:
        return MemoryItem(
            item_id=item_id,
            tier=MemoryTier.SEMANTIC,
            content=content,
            created_at=created,
            tags=tags or set(),
            metadata=metadata or {},
        )

    def _engine(self) -> RetrievalEngine:
        store = MemoryStore()
        engine = RetrievalEngine(store=store)
        items = [
            self._item(
                "m1",
                "budget review notes",
                created="2025-01-10T09:00:00+00:00",
                tags={"finance"},
                metadata={"people": ["alice", "bob"], "project": "alpha"},
            ),
            self._item(
                "m2",
                "budget planning for launch",
                created="2025-03-05T09:00:00+00:00",
                tags={"ops"},
                metadata={"person": "carol", "project": "beta"},
            ),
            self._item(
                "m3",
                "launch party playlist",
                created="2025-04-01T09:00:00+00:00",
                tags={"fun"},
            ),
        ]
        for item in items:
            store.add(item)
            engine.index_item(item)
        return engine

    def _ids(self, engine, query: str) -> list[str]:
        return [r.item_id for r in engine.search_parsed(parse_query(query))]

    def test_free_text_only_matches_both_budget_items(self):
        assert sorted(self._ids(self._engine(), "budget")) == ["m1", "m2"]

    def test_tag_filter_narrows_results(self):
        assert self._ids(self._engine(), "budget tag:finance") == ["m1"]

    def test_person_filter_reads_metadata_list_and_scalar(self):
        assert self._ids(self._engine(), "budget person:bob") == ["m1"]
        assert self._ids(self._engine(), "budget person:carol") == ["m2"]

    def test_project_filter(self):
        assert self._ids(self._engine(), "budget project:beta") == ["m2"]

    def test_before_is_exclusive(self):
        assert self._ids(self._engine(), "budget before:2025-03-05T09:00:00+00:00") == ["m1"]

    def test_after_is_inclusive(self):
        assert self._ids(self._engine(), "budget after:2025-03-05T09:00:00+00:00") == ["m2"]

    def test_on_matches_utc_day(self):
        assert self._ids(self._engine(), "budget on:2025-03-05") == ["m2"]

    def test_combined_filters_are_conjunctive(self):
        assert self._ids(self._engine(), "budget person:alice project:beta") == []
        assert self._ids(self._engine(), "budget person:alice project:alpha") == ["m1"]

    def test_filter_only_query_returns_zero_scores(self):
        engine = self._engine()
        results = engine.search_parsed(parse_query("tag:finance"))
        assert [r.item_id for r in results] == ["m1"]
        assert results[0].score == 0.0

    def test_unparseable_temporal_filter_is_ignored(self):
        assert sorted(self._ids(self._engine(), "budget before:garbage")) == ["m1", "m2"]

    def test_undated_item_fails_temporal_filter(self):
        engine = self._engine()
        undated = self._item("m4", "budget archive without a date")
        engine.store.add(undated)
        engine.index_item(undated)
        assert sorted(self._ids(engine, "budget")) == ["m1", "m2", "m4"]
        assert self._ids(engine, "budget before:2026-01-01") == ["m1", "m2"]
