"""Long simulated decay: convergence, protection, and monotone shrinkage.

A seeded store mixes protected items (pinned, tagged, held) with plain
low-salience memories created long before the simulation starts. Over
400 simulated days everything unprotected must settle into a steady
state while protected items survive untouched.
"""

from mnemofold.decay import DecayEngine, find_steady_state
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier

START = "2026-06-01T00:00:00+00:00"
CREATED = "2025-01-01T00:00:00+00:00"


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add(
        MemoryItem(
            item_id="plain-1",
            tier=MemoryTier.EPISODIC,
            content="old note",
            salience=0.05,
            created_at=CREATED,
            last_accessed=CREATED,
        )
    )
    store.add(
        MemoryItem(
            item_id="plain-2",
            tier=MemoryTier.WORKING,
            content="old task",
            salience=0.02,
            created_at=CREATED,
            last_accessed=CREATED,
        )
    )
    store.add(
        MemoryItem(
            item_id="pinned",
            tier=MemoryTier.EPISODIC,
            content="pinned memory",
            salience=0.01,
            created_at=CREATED,
            last_accessed=CREATED,
            pinned=True,
        )
    )
    store.add(
        MemoryItem(
            item_id="tagged",
            tier=MemoryTier.EPISODIC,
            content="legal hold tag",
            salience=0.01,
            created_at=CREATED,
            last_accessed=CREATED,
            tags={"legal_hold"},
        )
    )
    return store


class TestDecayConvergence:
    def test_simulation_settles(self):
        store = make_store()
        engine = DecayEngine()
        engine.place_hold("plain-1", reason="audit")  # protect one plain item too
        results = engine.simulate(store, START, days=400)
        assert len(results) == 400
        steady = find_steady_state(results)
        assert steady is not None
        for row in results[steady:]:
            assert row["demoted"] == 0
            assert row["tombstoned"] == 0
            assert row["purged"] == 0

    def test_protected_items_survive_to_the_end(self):
        store = make_store()
        engine = DecayEngine()
        engine.place_hold("plain-1", reason="audit")
        engine.simulate(store, START, days=400)
        for pid in ("pinned", "tagged", "plain-1"):
            assert store.peek(pid) is not None, pid

    def test_unprotected_items_eventually_purged(self):
        store = make_store()
        engine = DecayEngine()
        engine.simulate(store, START, days=400)
        assert store.peek("plain-2") is None

    def test_total_items_never_increases(self):
        store = make_store()
        results = DecayEngine().simulate(store, START, days=200)
        totals = [row["total_items"] for row in results]
        assert totals == sorted(totals, reverse=True)

    def test_simulation_is_deterministic(self):
        a = DecayEngine().simulate(make_store(), START, days=120)
        b = DecayEngine().simulate(make_store(), START, days=120)
        assert a == b
