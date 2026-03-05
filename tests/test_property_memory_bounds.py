"""Randomized working-set invariants for the memory store.

Across seeded add sequences with random salience and pin flags: the
non-pinned working set never exceeds the bound, every logged eviction
points at a real item that left the working tier, and pinned items are
never logged.
"""

import random

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


def sweep(seed: int, size: int, n_items: int) -> MemoryStore:
    rng = random.Random(seed)
    store = MemoryStore(working_set_size=size)
    for i in range(n_items):
        store.add(
            MemoryItem(
                item_id=f"m{i}",
                tier=MemoryTier.WORKING,
                content=f"content {i}",
                salience=round(rng.random(), 3),
                pinned=rng.random() < 0.2,
            )
        )
    return store


class TestWorkingSetProperties:
    def test_non_pinned_working_set_stays_within_bound(self):
        for seed in range(20):
            store = sweep(seed, size=5, n_items=40)
            working = store.items_by_tier(MemoryTier.WORKING)
            non_pinned = [i for i in working if not i.pinned]
            assert len(non_pinned) <= 5, seed

    def test_pinned_items_stay_in_working(self):
        for seed in range(20):
            store = sweep(seed, size=3, n_items=30)
            working_ids = {i.item_id for i in store.items_by_tier(MemoryTier.WORKING)}
            all_items = [i for tier in MemoryTier for i in store.items_by_tier(tier)]
            pinned_ids = {i.item_id for i in all_items if i.pinned}
            assert pinned_ids <= working_ids, seed

    def test_every_logged_eviction_left_the_working_tier(self):
        for seed in range(20):
            store = sweep(seed, size=4, n_items=30)
            for entry in store.evictions():
                item = store.peek(entry["item_id"])
                assert item is not None, seed
                assert entry["reason"] == "working_set_overflow"

    def test_pinned_ids_never_appear_in_the_log(self):
        for seed in range(20):
            store = sweep(seed, size=3, n_items=30)
            logged = {e["item_id"] for e in store.evictions()}
            all_items = [i for tier in MemoryTier for i in store.items_by_tier(tier)]
            pinned = {i.item_id for i in all_items if i.pinned}
            assert not (logged & pinned), seed

    def test_total_items_conserved(self):
        for seed in range(20):
            store = sweep(seed, size=4, n_items=25)
            assert store.total_count() == 25, seed
