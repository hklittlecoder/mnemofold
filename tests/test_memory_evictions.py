"""Working-set eviction audit trail."""

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


def working_item(item_id: str, salience: float, pinned: bool = False) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        tier=MemoryTier.WORKING,
        content=f"content {item_id}",
        salience=salience,
        pinned=pinned,
    )


class TestEvictionLog:
    def test_overflow_evicts_lowest_salience_and_logs_it(self):
        store = MemoryStore(working_set_size=2)
        store.add(working_item("m1", 0.9))
        store.add(working_item("m2", 0.5))
        store.add(working_item("m3", 0.7))
        assert store.peek("m2").tier == MemoryTier.EPISODIC
        assert store.evictions() == [{"item_id": "m2", "reason": "working_set_overflow"}]

    def test_no_eviction_under_the_bound(self):
        store = MemoryStore(working_set_size=5)
        store.add(working_item("m1", 0.1))
        store.add(working_item("m2", 0.2))
        assert store.evictions() == []

    def test_pinned_items_are_never_logged(self):
        store = MemoryStore(working_set_size=1)
        store.add(working_item("pin", 0.1, pinned=True))
        store.add(working_item("m2", 0.9))
        logged_ids = [e["item_id"] for e in store.evictions()]
        assert "pin" not in logged_ids
        assert store.peek("pin").tier == MemoryTier.WORKING

    def test_log_grows_monotonically(self):
        store = MemoryStore(working_set_size=1)
        for i in range(5):
            store.add(working_item(f"m{i}", 0.1 * i))
        # each add after the first evicts the previous lowest-salience item
        assert [e["item_id"] for e in store.evictions()] == ["m0", "m1", "m2", "m3"]

    def test_returned_log_is_a_copy(self):
        store = MemoryStore(working_set_size=1)
        store.add(working_item("m1", 0.1))
        store.add(working_item("m2", 0.9))
        log = store.evictions()
        log.append({"item_id": "fake", "reason": "injected"})
        assert all(e["item_id"] != "fake" for e in store.evictions())

    def test_deterministic_tie_break_is_logged_in_order(self):
        store = MemoryStore(working_set_size=1)
        store.add(working_item("b", 0.5))
        store.add(working_item("a", 0.5))
        # equal salience -> item_id tie-break evicts "a"
        assert store.evictions()[-1]["item_id"] == "a"
