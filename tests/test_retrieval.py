"""Tests for retrieval module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mnemofold.deletion import DeletionReason
from mnemofold.factory import WorkHistoryFactory
from mnemofold.graph import Edge, EdgeType, Node, NodeType, WorkstreamGraph
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import (
    BM25Index,
    FusionWeights,
    ParsedQuery,
    RetrievalEngine,
    build_deletion_engine,
    forget,
    fuse_score,
    mmr_rerank,
    parse_query,
    safe_index,
    tokenize,
)

FORGET_NOW = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


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


class TestIndexBookkeeping:
    """Black-box checks that length statistics survive add/remove/re-add."""

    def _corpus(self, idx: BM25Index) -> None:
        idx.add("d1", "alpha beta gamma")
        idx.add("d2", "alpha alpha beta delta epsilon zeta")
        idx.add("d3", "gamma delta")

    def test_add_remove_restores_identical_scores(self):
        before = BM25Index()
        self._corpus(before)
        baseline = before.search("alpha beta")

        after = BM25Index()
        self._corpus(after)
        after.add("tmp", "unrelated words about gardening and cooking")
        after.remove("tmp")
        assert after.search("alpha beta") == baseline

    def test_readd_replaces_document(self):
        idx = BM25Index()
        self._corpus(idx)
        idx.add("d1", "totally different content about orbit mechanics")
        assert idx.doc_count() == 3
        assert [d for d, _ in idx.search("alpha beta")] == ["d2"]
        assert [d for d, _ in idx.search("orbit")] == ["d1"]

    def test_remove_missing_id_is_noop(self):
        idx = BM25Index()
        self._corpus(idx)
        baseline = idx.search("alpha")
        idx.remove("nope")
        assert idx.search("alpha") == baseline
        assert idx.doc_count() == 3

    def test_removing_a_doc_changes_length_statistics(self):
        # avgdl feeds BM25 normalization, so removing one long doc must
        # observably shift scores of the remaining docs.
        idx = BM25Index()
        idx.add("long", "alpha " + " ".join(f"pad{i}" for i in range(200)))
        idx.add("short", "alpha beta")
        with_long = dict(idx.search("alpha"))
        idx.remove("long")
        without_long = dict(idx.search("alpha"))
        assert with_long["short"] != without_long["short"]

    def test_remove_everything_returns_to_genesis(self):
        idx = BM25Index()
        self._corpus(idx)
        for item_id in ("d1", "d2", "d3"):
            idx.remove(item_id)
        assert idx.doc_count() == 0
        assert idx.search("alpha") == []


class TestFusion:
    def test_weight_validation(self):
        with pytest.raises(ValueError, match="non-negative"):
            FusionWeights(relevance=-1.0)
        with pytest.raises(ValueError, match="not all be zero"):
            FusionWeights(relevance=0.0, importance=0.0, recency=0.0)
        with pytest.raises(ValueError, match="half_life_days"):
            FusionWeights(half_life_days=0.0)

    def test_recency_halves_at_half_life(self):
        w = FusionWeights(relevance=0.0, importance=0.0, recency=1.0, half_life_days=10.0)
        assert fuse_score(0.0, 0.0, 0.0, w) == 1.0
        assert fuse_score(0.0, 0.0, 10.0, w) == 0.5
        assert fuse_score(0.0, 0.0, 20.0, w) == 0.25

    def test_undated_items_get_no_recency(self):
        w = FusionWeights(relevance=0.0, importance=0.0, recency=1.0)
        assert fuse_score(0.0, 0.0, None, w) == 0.0

    def test_negative_age_clamps_to_fresh(self):
        w = FusionWeights(relevance=0.0, importance=0.0, recency=1.0)
        assert fuse_score(0.0, 0.0, -3.0, w) == 1.0

    def test_weighted_sum_is_quantized(self):
        w = FusionWeights(relevance=1.0, importance=1.0, recency=0.0)
        assert fuse_score(0.5, 0.25, None, w) == 0.75
        thirds = FusionWeights(relevance=1.0 / 3.0, importance=0.0, recency=0.0)
        assert fuse_score(1.0, 0.0, None, thirds) == 0.333333


class TestFusionInEngine:
    NOW = "2025-06-15T00:00:00+00:00"

    def _engine(self) -> RetrievalEngine:
        store = MemoryStore()
        engine = RetrievalEngine(store=store)
        old = MemoryItem(
            item_id="old",
            tier=MemoryTier.SEMANTIC,
            content="release report draft",
            salience=0.2,
            created_at="2025-01-01T00:00:00+00:00",
        )
        new = MemoryItem(
            item_id="new",
            tier=MemoryTier.SEMANTIC,
            content="release report final",
            salience=0.9,
            created_at="2025-06-01T00:00:00+00:00",
        )
        store.add(old)
        store.add(new)
        engine.index_item(old)
        engine.index_item(new)
        return engine

    def test_equal_relevance_recency_prefers_newer(self):
        engine = self._engine()
        weights = FusionWeights(relevance=1.0, recency=1.0, half_life_days=30.0)
        results = engine.search("release report", lambda_mmr=1.0, fusion=weights, now=self.NOW)
        assert results[0].item_id == "new"

    def test_importance_uses_salience(self):
        engine = self._engine()
        weights = FusionWeights(relevance=0.0, importance=1.0)
        results = engine.search("release report", lambda_mmr=1.0, fusion=weights)
        assert results[0].item_id == "new"

    def test_recency_weight_without_now_raises(self):
        engine = self._engine()
        with pytest.raises(ValueError, match="now"):
            engine.search("release report", fusion=FusionWeights(recency=1.0))

    def test_reasons_explain_components(self):
        engine = self._engine()
        weights = FusionWeights(relevance=1.0, importance=1.0, recency=1.0)
        results = engine.search("release report", fusion=weights, now=self.NOW)
        joined = " ".join(results[0].reasons)
        assert "relevance=" in joined
        assert "importance=" in joined
        assert "recency=" in joined
        assert joined.startswith("score=")

    def test_fusion_is_deterministic(self):
        weights = FusionWeights(relevance=1.0, importance=0.5, recency=0.5)
        first = [
            (r.item_id, r.score)
            for r in self._engine().search("release report", fusion=weights, now=self.NOW)
        ]
        second = [
            (r.item_id, r.score)
            for r in self._engine().search("release report", fusion=weights, now=self.NOW)
        ]
        assert first == second


class TestGraphExpansion:
    def _engine(self, with_graph: bool = True) -> RetrievalEngine:
        store = MemoryStore()
        graph = None
        if with_graph:
            graph = WorkstreamGraph()
            graph.add_node(Node(node_id="alice", node_type=NodeType.PERSON, label="Alice"))
            graph.add_node(Node(node_id="alpha", node_type=NodeType.PROJECT, label="Alpha"))
            graph.add_node(Node(node_id="zeta", node_type=NodeType.PROJECT, label="Zeta"))
            graph.add_edge(
                Edge(
                    edge_id="e1",
                    edge_type=EdgeType.PARTICIPATES,
                    source_id="alice",
                    target_id="alpha",
                )
            )
        engine = RetrievalEngine(store=store, graph=graph)
        items = [
            MemoryItem(
                item_id="m-hit",
                tier=MemoryTier.EPISODIC,
                content="quarterly report draft",
                metadata={"entity_ids": ["alice"]},
            ),
            MemoryItem(
                item_id="m-rel",
                tier=MemoryTier.EPISODIC,
                content="alpha milestone notes",
                metadata={"entity_ids": ["alpha"]},
            ),
            MemoryItem(
                item_id="m-off",
                tier=MemoryTier.EPISODIC,
                content="zeta unrelated report",
                metadata={"entity_ids": ["zeta"]},
            ),
        ]
        for item in items:
            store.add(item)
            engine.index_item(item)
        return engine

    def test_expansion_adds_graph_neighbors(self):
        engine = self._engine()
        plain = {r.item_id for r in engine.search("report")}
        assert plain == {"m-hit", "m-off"}
        expanded = {r.item_id for r in engine.search("report", expand_graph=True)}
        assert expanded == {"m-hit", "m-off", "m-rel"}

    def test_expansion_reason_and_discounted_score(self):
        engine = self._engine()
        results = {r.item_id: r for r in engine.search("report", expand_graph=True)}
        base = results["m-hit"].score
        assert results["m-rel"].score == pytest.approx(base * 0.5)
        assert any(
            "expanded_via=graph:alice->alpha" in reason for reason in results["m-rel"].reasons
        )
        assert not any("expanded_via" in reason for reason in results["m-hit"].reasons)

    def test_discount_zero_still_expands_at_zero_score(self):
        engine = self._engine()
        results = {
            r.item_id: r for r in engine.search("report", expand_graph=True, expansion_discount=0.0)
        }
        assert "m-rel" in results
        assert results["m-rel"].score == 0.0

    def test_without_graph_expansion_is_noop(self):
        engine = self._engine(with_graph=False)
        results = {r.item_id for r in engine.search("report", expand_graph=True)}
        assert results == {"m-hit", "m-off"}

    def test_expansion_is_deterministic(self):
        first = [
            (r.item_id, round(r.score, 6))
            for r in self._engine().search("report", expand_graph=True)
        ]
        second = [
            (r.item_id, round(r.score, 6))
            for r in self._engine().search("report", expand_graph=True)
        ]
        assert first == second

    def test_parsed_search_supports_expansion(self):
        engine = self._engine()
        results = {
            r.item_id for r in engine.search_parsed(parse_query("report"), expand_graph=True)
        }
        assert results == {"m-hit", "m-off", "m-rel"}


class TestAsOfRetrieval:
    def _engine(self) -> RetrievalEngine:
        store = MemoryStore()
        engine = RetrievalEngine(store=store)
        early = MemoryItem(
            item_id="early",
            tier=MemoryTier.EPISODIC,
            content="migration plan draft",
            created_at="2025-01-10T00:00:00+00:00",
        )
        store.add(early)
        engine.index_item(early)
        return engine

    def _add_later(self, engine: RetrievalEngine) -> None:
        later = MemoryItem(
            item_id="later",
            tier=MemoryTier.EPISODIC,
            content="migration plan final",
            created_at="2025-05-10T00:00:00+00:00",
        )
        engine.store.add(later)
        engine.index_item(later)

    def test_items_created_after_bound_are_excluded(self):
        engine = self._engine()
        self._add_later(engine)
        ids = [
            r.item_id for r in engine.search("migration plan", as_of="2025-03-01T00:00:00+00:00")
        ]
        assert ids == ["early"]
        ids_all = {r.item_id for r in engine.search("migration plan")}
        assert ids_all == {"early", "later"}

    def test_bound_is_inclusive(self):
        engine = self._engine()
        ids = [r.item_id for r in engine.search("migration", as_of="2025-01-10T00:00:00+00:00")]
        assert ids == ["early"]

    def test_as_of_answers_are_stable_under_later_additions(self):
        # The id set and order must not change when later items arrive;
        # raw BM25 scores may shift because corpus statistics (idf, avgdl)
        # legitimately evolve as the index grows.
        engine = self._engine()
        bound = "2025-03-01T00:00:00+00:00"
        before = [r.item_id for r in engine.search("migration plan", as_of=bound)]
        self._add_later(engine)
        after = [r.item_id for r in engine.search("migration plan", as_of=bound)]
        assert before == after == ["early"]

    def test_undated_items_stay_visible(self):
        engine = self._engine()
        undated = MemoryItem(
            item_id="undated", tier=MemoryTier.EPISODIC, content="migration trivia"
        )
        engine.store.add(undated)
        engine.index_item(undated)
        ids = {r.item_id for r in engine.search("migration", as_of="2025-02-01T00:00:00+00:00")}
        assert ids == {"early", "undated"}

    def test_invalid_as_of_disables_filter(self):
        engine = self._engine()
        self._add_later(engine)
        ids = {r.item_id for r in engine.search("migration plan", as_of="not-a-date")}
        assert ids == {"early", "later"}

    def test_parsed_search_honors_as_of(self):
        engine = self._engine()
        self._add_later(engine)
        results = engine.search_parsed(
            parse_query("migration plan"), as_of="2025-03-01T00:00:00+00:00"
        )
        assert [r.item_id for r in results] == ["early"]

    def test_as_of_also_screens_graph_expansions(self):
        store = MemoryStore()
        graph = WorkstreamGraph()
        graph.add_node(Node(node_id="alice", node_type=NodeType.PERSON, label="Alice"))
        graph.add_node(Node(node_id="alpha", node_type=NodeType.PROJECT, label="Alpha"))
        graph.add_edge(
            Edge(
                edge_id="e1",
                edge_type=EdgeType.PARTICIPATES,
                source_id="alice",
                target_id="alpha",
            )
        )
        engine = RetrievalEngine(store=store, graph=graph)
        base = MemoryItem(
            item_id="base",
            tier=MemoryTier.EPISODIC,
            content="migration report",
            created_at="2025-01-01T00:00:00+00:00",
            metadata={"entity_ids": ["alice"]},
        )
        future = MemoryItem(
            item_id="future",
            tier=MemoryTier.EPISODIC,
            content="migration followup",
            created_at="2025-09-01T00:00:00+00:00",
            metadata={"entity_ids": ["alpha"]},
        )
        for item in (base, future):
            store.add(item)
            engine.index_item(item)
        ids = {
            r.item_id
            for r in engine.search(
                "migration", expand_graph=True, as_of="2025-03-01T00:00:00+00:00"
            )
        }
        assert ids == {"base"}


def _factory_engine(seed: int = 9, days: int = 30) -> RetrievalEngine:
    """Build a retrieval engine over a synthetic factory history."""
    factory = WorkHistoryFactory(seed=seed, days=days)
    events, _ = factory.generate()
    store = MemoryStore()
    engine = RetrievalEngine(store=store)
    for synthetic in events:
        event = synthetic.to_event()
        parts = [
            str(value)
            for key, value in sorted(event.content.items())
            if isinstance(value, str) and value
        ]
        item = MemoryItem(
            item_id=event.event_id,
            tier=MemoryTier.EPISODIC,
            content=" ".join(parts),
            title=str(event.event_type),
            created_at=event.timestamp.isoformat(),
            tags={event.event_type.value},
        )
        store.add(item)
        engine.index_item(item)
    return engine


class TestRetrievalPropertiesOnFactory:
    QUERIES = (
        "budget",
        "milestone",
        "meeting notes",
        "design doc",
        "review",
        "deadline",
        "alpha",
        "standup",
        "risk",
        "launch",
    )

    def test_citations_always_resolve(self):
        engine = _factory_engine()
        for query in self.QUERIES:
            assert engine.property_citations_resolve(query), query
            for result in engine.search(query):
                assert engine.store.get(result.item_id) is not None
                assert result.citation == f"[{result.item_id}]"

    def test_top_k_respected_and_ids_unique(self):
        engine = _factory_engine()
        for query in ("the", "project", "mail", "notes"):
            results = engine.search(query, top_k=5)
            assert len(results) <= 5
            ids = [r.item_id for r in results]
            assert len(ids) == len(set(ids))

    def test_repeated_search_is_deterministic(self):
        engine = _factory_engine()
        first = [(r.item_id, round(r.score, 6)) for r in engine.search("deadline review")]
        second = [(r.item_id, round(r.score, 6)) for r in engine.search("deadline review")]
        assert first == second

    def test_results_disappear_with_their_memory(self):
        engine = _factory_engine()
        results = engine.search("milestone")
        assert results
        victim = results[0].item_id
        engine.store.remove(victim)
        engine.index.remove(victim)
        after = engine.search("milestone")
        assert all(r.item_id != victim for r in after)
        assert engine.property_citations_resolve("milestone")


class TestSnippets:
    def _engine(self, content: str) -> RetrievalEngine:
        store = MemoryStore()
        engine = RetrievalEngine(store=store)
        item = MemoryItem(item_id="m1", tier=MemoryTier.SEMANTIC, content=content)
        store.add(item)
        engine.index_item(item)
        return engine

    def test_short_text_returned_verbatim(self):
        engine = self._engine("short note about budgets")
        result = engine.search("budgets")[0]
        assert result.snippet == "short note about budgets"

    def test_snippet_centers_on_match(self):
        filler = " ".join(f"filler{i}" for i in range(60))
        content = f"{filler} budget anomaly {filler}"
        engine = self._engine(content)
        result = engine.search("budget")[0]
        assert "budget" in result.snippet
        assert result.snippet.startswith("...")
        assert result.snippet.endswith("...")
        assert len(result.snippet) <= 120 + 6

    def test_match_near_head_has_no_lead_ellipsis(self):
        content = " ".join(f"word{i}" for i in range(60))
        engine = self._engine(content)
        result = engine.search("word1 word50")[0]
        # earliest match (word1) sits at the very start -> no lead ellipsis
        assert result.snippet.startswith("word0 word1")
        assert result.snippet.endswith("...")

    def test_unmatched_query_text_uses_head_truncation(self):
        content = " ".join(f"alpha{i}" for i in range(60))
        engine = self._engine(content)
        snippet = engine._make_snippet(content, "zzz qqq")
        assert snippet == content[:120] + "..."


class TestRetrievalBoundaries:
    def _engine(self) -> RetrievalEngine:
        store = MemoryStore()
        engine = RetrievalEngine(store=store)
        for item_id, content, tags in (
            ("a", "release report draft one", {"work"}),
            ("b", "release report draft two", {"work"}),
            ("c", "garden planning ideas", {"home"}),
        ):
            item = MemoryItem(
                item_id=item_id, tier=MemoryTier.SEMANTIC, content=content, tags=set(tags)
            )
            store.add(item)
            engine.index_item(item)
        return engine

    def test_empty_query_returns_nothing(self):
        assert self._engine().search("") == []

    def test_empty_index_returns_nothing(self):
        engine = RetrievalEngine(store=MemoryStore())
        assert engine.search("anything") == []

    def test_top_k_larger_than_corpus(self):
        results = self._engine().search("release report", top_k=99)
        assert {r.item_id for r in results} == {"a", "b"}

    def test_min_score_above_all_scores_filters_everything(self):
        assert self._engine().search("release", min_score=1e9) == []

    def test_tag_filter_with_no_overlap(self):
        assert self._engine().search("release", tags={"nonexistent"}) == []

    def test_tag_filter_keeps_matches(self):
        results = self._engine().search("planning", tags={"home"})
        assert [r.item_id for r in results] == ["c"]

    def test_mmr_lambda_extremes(self):
        self._engine()
        candidates = [("a", 3.0), ("b", 2.9), ("c", 1.0)]
        texts = {
            "a": "release report draft one",
            "b": "release report draft two",
            "c": "garden planning ideas",
        }
        assert mmr_rerank(candidates, texts, lambda_param=1.0, top_k=3) == ["a", "b", "c"]
        diverse = mmr_rerank(candidates, texts, lambda_param=0.0, top_k=3)
        assert diverse[0] == "a"
        assert diverse[1] == "c"  # dissimilar item promoted over near-duplicate

    def test_mmr_top_k_zero_and_empty_input(self):
        assert mmr_rerank([("a", 1.0)], {"a": "x"}, top_k=0) == []
        assert mmr_rerank([], {}, top_k=5) == []

    def test_mmr_is_deterministic_on_ties(self):
        candidates = [("a", 1.0), ("b", 1.0)]
        texts = {"a": "same text", "b": "same text"}
        first = mmr_rerank(candidates, texts, top_k=2)
        second = mmr_rerank(candidates, texts, top_k=2)
        assert first == second
        assert sorted(first) == ["a", "b"]

    def test_index_store_divergence_never_leaks_citations(self):
        engine = self._engine()
        engine.store.remove("a")  # index still knows "a"
        results = engine.search("release report")
        assert all(r.item_id != "a" for r in results)
        assert engine.property_citations_resolve("release report")


class TestDeletionWiring:
    def _engine(self) -> RetrievalEngine:
        store = MemoryStore()
        engine = RetrievalEngine(store=store)
        items = [
            MemoryItem(
                item_id="root",
                tier=MemoryTier.SEMANTIC,
                content="quarterly budget secrets",
                metadata={"cascade": ["derived"]},
            ),
            MemoryItem(
                item_id="derived",
                tier=MemoryTier.SEMANTIC,
                content="derived budget summary",
            ),
            MemoryItem(
                item_id="other",
                tier=MemoryTier.SEMANTIC,
                content="unrelated holiday notes",
            ),
        ]
        for item in items:
            store.add(item)
            engine.index_item(item)
        return engine

    def test_forget_cascades_and_clears_index(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        report = forget(deletion, "root", DeletionReason.FORGET, FORGET_NOW)
        assert report.total_deleted == 2  # root + derived
        assert engine.store.peek("root") is None
        assert engine.store.peek("derived") is None
        assert engine.store.peek("other") is not None
        assert "root" not in engine.index.ids()
        assert "derived" not in engine.index.ids()

    def test_deleted_content_not_searchable(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        assert engine.search("budget")
        forget(deletion, "root", DeletionReason.FORGET, FORGET_NOW)
        results = engine.search("budget")
        assert all(r.item_id not in {"root", "derived"} for r in results)

    def test_tombstone_blocks_reindex(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        forget(deletion, "root", DeletionReason.FORGET, FORGET_NOW)
        revived = MemoryItem(
            item_id="root", tier=MemoryTier.SEMANTIC, content="budget secrets return"
        )
        assert safe_index(engine, deletion, revived) is False
        assert engine.store.peek("root") is None

    def test_protected_item_blocks_cascade(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine, is_protected=lambda k: k == "derived")
        report = forget(deletion, "root", DeletionReason.FORGET, FORGET_NOW)
        assert "derived" in report.blocked
        assert engine.store.peek("derived") is not None

    def test_safe_index_allows_fresh_items(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        fresh = MemoryItem(item_id="fresh", tier=MemoryTier.SEMANTIC, content="new note")
        assert safe_index(engine, deletion, fresh) is True
        assert engine.store.peek("fresh") is not None

    def test_peek_does_not_record_access(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.EPISODIC, "c"))
        assert store.peek("i1") is not None
        assert store.peek("i1").access_count == 0
        assert store.get("i1") is not None
        assert store.peek("i1").access_count == 1

    def test_forget_missing_target_records_error(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        report = forget(deletion, "ghost", DeletionReason.FORGET, FORGET_NOW)
        assert report.total_deleted == 0
        assert any("ghost" in err for err in report.errors)


class TestNoResurrection:
    """Deleted memories must never reappear through any query path."""

    def _engine(self) -> RetrievalEngine:
        store = MemoryStore()
        graph = WorkstreamGraph()
        graph.add_node(Node(node_id="alice", node_type=NodeType.PERSON, label="Alice"))
        graph.add_node(Node(node_id="alpha", node_type=NodeType.PROJECT, label="Alpha"))
        graph.add_edge(
            Edge(edge_id="e1", edge_type=EdgeType.OWNS, source_id="alice", target_id="alpha")
        )
        engine = RetrievalEngine(store=store, graph=graph)
        items = [
            MemoryItem(
                item_id="secret",
                tier=MemoryTier.SEMANTIC,
                content="alpha budget secret numbers",
                tags={"finance"},
                created_at="2025-01-01T00:00:00+00:00",
                metadata={"entity_ids": ["alice"], "cascade": ["shadow"]},
            ),
            MemoryItem(
                item_id="shadow",
                tier=MemoryTier.SEMANTIC,
                content="alpha budget shadow copy",
                metadata={"entity_ids": ["alpha"]},
            ),
            MemoryItem(
                item_id="keeper",
                tier=MemoryTier.SEMANTIC,
                content="alpha release plan",
                tags={"finance"},
                created_at="2025-01-01T00:00:00+00:00",
                metadata={"entity_ids": ["alice"]},
            ),
        ]
        for item in items:
            store.add(item)
            engine.index_item(item)
        return engine

    def test_no_path_resurfaces_deleted_content(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        forget(deletion, "secret", DeletionReason.FORGET, FORGET_NOW)
        gone = {"secret", "shadow"}

        free_text = {r.item_id for r in engine.search("alpha budget")}
        assert not (free_text & gone)

        filtered = {r.item_id for r in engine.search_parsed(parse_query("budget tag:finance"))}
        assert not (filtered & gone)

        expanded = {r.item_id for r in engine.search("alpha budget", expand_graph=True)}
        assert not (expanded & gone)

        asof = {r.item_id for r in engine.search("alpha budget", as_of="2025-06-01T00:00:00+00:00")}
        assert not (asof & gone)

        # the survivor is still findable
        assert "keeper" in free_text

    def test_deleted_ids_absent_from_index_listing(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        forget(deletion, "secret", DeletionReason.FORGET, FORGET_NOW)
        ids = set(engine.index.ids())
        assert "secret" not in ids and "shadow" not in ids
        assert "keeper" in ids

    def test_reingestion_of_source_does_not_revive(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        forget(deletion, "secret", DeletionReason.FORGET, FORGET_NOW)
        revived = MemoryItem(
            item_id="secret", tier=MemoryTier.SEMANTIC, content="alpha budget secret numbers"
        )
        assert safe_index(engine, deletion, revived) is False
        assert engine.search("alpha budget secret") and all(
            r.item_id != "secret" for r in engine.search("alpha budget secret")
        )

    def test_citations_still_resolve_after_deletion(self):
        engine = self._engine()
        deletion = build_deletion_engine(engine)
        forget(deletion, "secret", DeletionReason.FORGET, FORGET_NOW)
        assert engine.property_citations_resolve("alpha budget")
