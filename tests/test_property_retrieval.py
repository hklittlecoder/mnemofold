"""Cross-module property tests for retrieval: citations and deletion.

The properties here are structural invariants of the machinery — they
must hold for EVERY seeded random configuration, not on average. Inputs
are small so the whole file runs fast. Nothing here is a quality claim
about any corpus; it verifies the guarantees the framework makes:

* every citation in every result resolves to a live memory;
* forgotten ids never resurface through any query path;
* tombstones block re-ingestion of the same content.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.deletion import DeletionReason
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import (
    RetrievalEngine,
    build_deletion_engine,
    forget,
    parse_query,
    safe_index,
)

WORDS = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "release",
    "budget",
    "report",
    "plan",
    "risk",
    "launch",
    "review",
    "design",
    "sync",
    "update",
]

QUERIES = (
    "alpha",
    "beta release",
    "tag:red",
    "project:alpha budget",
    "report before:2025-01-02T00:00:00+00:00",
    "",
)

FORGET_NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _random_store(rng: random.Random, n: int) -> tuple[RetrievalEngine, list[MemoryItem]]:
    store = MemoryStore()
    engine = RetrievalEngine(store=store)
    items: list[MemoryItem] = []
    for i in range(n):
        text = " ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 10)))
        item = MemoryItem(
            item_id=f"m{i:03d}",
            tier=MemoryTier.SEMANTIC,
            content=text,
            title=f"item {i}",
            created_at=(datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=i)).isoformat(),
            tags={rng.choice(["red", "green", "blue"])},
            metadata={"project": rng.choice(["alpha", "beta"])},
        )
        store.add(item)
        engine.index_item(item)
        items.append(item)
    return engine, items


class TestCitationProperty:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_citations_always_resolve(self, seed):
        rng = random.Random(seed)
        engine, _items = _random_store(rng, 25)
        for query in QUERIES:
            results = engine.search_parsed(parse_query(query), top_k=8)
            for result in results:
                assert engine.store.peek(result.item_id) is not None
                assert result.citation == f"[{result.item_id}]"

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_results_unique_and_bounded(self, seed):
        rng = random.Random(seed)
        engine, _items = _random_store(rng, 25)
        for query in QUERIES:
            results = engine.search_parsed(parse_query(query), top_k=6)
            ids = [r.item_id for r in results]
            assert len(ids) == len(set(ids))
            assert len(ids) <= 6

    @pytest.mark.parametrize("seed", [1, 2])
    def test_store_index_divergence_never_leaks(self, seed):
        rng = random.Random(seed)
        engine, items = _random_store(rng, 15)
        engine.store.remove(items[0].item_id)  # simulate an inconsistent store
        for query in QUERIES:
            for result in engine.search(query, top_k=10):
                assert result.item_id != items[0].item_id
                assert engine.store.peek(result.item_id) is not None


class TestNoResurrectionProperty:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_deleted_ids_never_resurface(self, seed):
        rng = random.Random(seed + 100)
        engine, items = _random_store(rng, 20)
        deletion = build_deletion_engine(engine)
        victims = [items[i].item_id for i in rng.sample(range(20), 5)]
        for victim in victims:
            report = forget(deletion, victim, DeletionReason.FORGET, FORGET_NOW)
            assert any(entry.key == victim for entry in report.deleted)

        victim_set = set(victims)
        for query in QUERIES:
            parsed_hits = {r.item_id for r in engine.search_parsed(parse_query(query), top_k=20)}
            plain_hits = {r.item_id for r in engine.search(query, top_k=20)}
            assert not (parsed_hits & victim_set)
            assert not (plain_hits & victim_set)
        assert not (set(engine.index.ids()) & victim_set)

    @pytest.mark.parametrize("seed", [1, 2])
    def test_tombstone_blocks_reingestion(self, seed):
        rng = random.Random(seed + 200)
        engine, items = _random_store(rng, 10)
        deletion = build_deletion_engine(engine)
        victim = items[0]
        forget(deletion, victim.item_id, DeletionReason.FORGET, FORGET_NOW)
        revived = MemoryItem(victim.item_id, MemoryTier.SEMANTIC, "alpha budget report")
        assert safe_index(engine, deletion, revived) is False
        assert engine.store.peek(victim.item_id) is None
        assert victim.item_id not in engine.index.ids()

    @pytest.mark.parametrize("seed", [1, 2])
    def test_survivors_still_reachable(self, seed):
        rng = random.Random(seed + 300)
        engine, items = _random_store(rng, 12)
        deletion = build_deletion_engine(engine)
        forget(deletion, items[0].item_id, DeletionReason.FORGET, FORGET_NOW)
        survivor = items[1].item_id
        assert engine.store.peek(survivor) is not None
        assert survivor in engine.index.ids()
        assert engine.property_citations_resolve("alpha beta release")
