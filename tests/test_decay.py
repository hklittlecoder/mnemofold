"""Tests for decay and forgetting."""

from __future__ import annotations

import pytest

from mnemofold.decay import (
    DEFAULT_POLICIES,
    DecayEngine,
    RetentionPolicy,
)
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


class TestRetentionPolicy:
    def test_half_life(self):
        p = RetentionPolicy(MemoryTier.SEMANTIC, half_life_days=30.0)
        assert p.decay_factor(30.0) == pytest.approx(0.5, rel=0.01)

    def test_zero_days(self):
        p = RetentionPolicy(MemoryTier.SEMANTIC, half_life_days=30.0)
        assert p.decay_factor(0.0) == 1.0

    def test_pinned_no_decay(self):
        p = RetentionPolicy(MemoryTier.EPISODIC, half_life_days=1.0, min_salience=0.5)
        item = MemoryItem("i1", MemoryTier.EPISODIC, "x", salience=0.1, pinned=True)
        assert not p.should_decay(item, "2025-01-01T00:00:00+00:00")


class TestDecayEngine:
    def test_decay_demotes_items(self):
        store = MemoryStore()
        for i in range(10):
            item = MemoryItem(
                f"ep_{i}",
                MemoryTier.EPISODIC,
                f"content {i}",
                salience=0.3,
                created_at="2024-01-01T00:00:00+00:00",
                last_accessed="2024-01-01T00:00:00+00:00",
            )
            store.add(item)
        engine = DecayEngine()
        stats = engine.apply_decay(store, "2024-06-01T00:00:00+00:00")
        assert stats["demoted"] > 0
        assert len(store.items_by_tier(MemoryTier.SEMANTIC)) > 0

    def test_protected_not_decayed(self):
        store = MemoryStore()
        prot = MemoryItem(
            "p1",
            MemoryTier.EPISODIC,
            "imp",
            salience=0.1,
            tags={"legal_hold"},
            created_at="2024-01-01T00:00:00+00:00",
            last_accessed="2024-01-01T00:00:00+00:00",
        )
        normal = MemoryItem(
            "n1",
            MemoryTier.EPISODIC,
            "norm",
            salience=0.1,
            created_at="2024-01-01T00:00:00+00:00",
            last_accessed="2024-01-01T00:00:00+00:00",
        )
        store.add(prot)
        store.add(normal)
        engine = DecayEngine()
        engine.apply_decay(store, "2025-01-01T00:00:00+00:00")
        assert store.get("p1") is not None

    def test_pinned_not_decayed(self):
        store = MemoryStore()
        item = MemoryItem(
            "pin1",
            MemoryTier.WORKING,
            "x",
            salience=0.1,
            pinned=True,
            created_at="2024-01-01T00:00:00+00:00",
            last_accessed="2024-01-01T00:00:00+00:00",
        )
        store.add(item)
        engine = DecayEngine()
        stats = engine.apply_decay(store, "2025-01-01T00:00:00+00:00")
        assert stats["protected_skipped"] >= 1

    def test_property_protected_never_deleted(self):
        store = MemoryStore()
        for i in range(15):
            item = MemoryItem(
                f"it_{i}",
                MemoryTier.EPISODIC,
                f"c {i}",
                salience=0.5,
                pinned=(i % 5 == 0),
                created_at="2024-01-01T00:00:00+00:00",
                last_accessed="2024-01-01T00:00:00+00:00",
            )
            if i % 7 == 0:
                item.tags.add("legal_hold")
            store.add(item)
        engine = DecayEngine()
        assert engine.property_protected_never_deleted(store, "2025-06-01T00:00:00+00:00")

    def test_simulation(self):
        store = MemoryStore()
        engine = DecayEngine()
        results = engine.simulate(store, "2024-01-01T00:00:00+00:00", days=30)
        assert len(results) == 30
        assert "total_items" in results[0]

    def test_default_policies_all_tiers(self):
        assert len(DEFAULT_POLICIES) == 4
        for tier in MemoryTier:
            assert tier in DEFAULT_POLICIES

    def test_working_decays_fastest(self):
        store = MemoryStore()
        for tier in MemoryTier:
            item = MemoryItem(
                f"i_{tier}",
                tier,
                "x",
                salience=0.5,
                created_at="2024-01-01T00:00:00+00:00",
                last_accessed="2024-01-01T00:00:00+00:00",
            )
            store.add(item)
        engine = DecayEngine()
        engine.apply_decay(store, "2024-01-08T00:00:00+00:00")
        # Working tier should be empty (all demoted)
        assert len(store.items_by_tier(MemoryTier.WORKING)) == 0
        # Semantic should still have items
        assert len(store.items_by_tier(MemoryTier.SEMANTIC)) >= 1


class TestProtectedPropertyCheck:
    def _store_with_protected(self) -> MemoryStore:
        store = MemoryStore()
        store.add(
            MemoryItem(
                "hold1",
                MemoryTier.PROCEDURAL,
                "audit records",
                salience=0.0,
                created_at="2020-01-01T00:00:00+00:00",
                tags={"legal_hold"},
            )
        )
        return store

    def test_healthy_run_satisfies_property(self):
        engine = DecayEngine()
        store = self._store_with_protected()
        assert engine.property_protected_never_deleted(store, "2025-06-01T00:00:00+00:00")

    def test_detects_vanishing_protected_item(self):
        engine = DecayEngine()
        store = self._store_with_protected()
        original = engine.apply_decay

        def buggy_decay(target: MemoryStore, now: str) -> dict:
            stats = original(target, now)
            target.remove("hold1")  # simulate a faulty code path
            return stats

        engine.apply_decay = buggy_decay  # type: ignore[method-assign]
        assert engine.property_protected_never_deleted(store, "2025-06-01T00:00:00+00:00") is False

    def test_property_does_not_flag_unprotected_removals(self):
        engine = DecayEngine()
        store = MemoryStore()
        store.add(
            MemoryItem(
                "temp",
                MemoryTier.PROCEDURAL,
                "scratch",
                salience=0.0,
                created_at="2020-01-01T00:00:00+00:00",
            )
        )
        original = engine.apply_decay

        def removes_unprotected(target: MemoryStore, now: str) -> dict:
            stats = original(target, now)
            target.remove("temp")
            return stats

        engine.apply_decay = removes_unprotected  # type: ignore[method-assign]
        # "temp" is not protected, so the invariant says nothing about it
        assert engine.property_protected_never_deleted(store, "2025-06-01T00:00:00+00:00")
