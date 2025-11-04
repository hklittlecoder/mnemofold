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

    def test_access_boost_extends_half_life(self):
        p = RetentionPolicy(MemoryTier.SEMANTIC, half_life_days=10.0, access_boost=0.5)
        item = MemoryItem(
            "i1",
            MemoryTier.SEMANTIC,
            "x",
            salience=1.0,
            created_at="2024-01-01T00:00:00+00:00",
        )
        before = p.decayed_salience(item, "2024-01-11T00:00:00+00:00")
        p.record_access(item, "2024-01-11T00:00:00+00:00")
        after = p.decayed_salience(item, "2024-01-21T00:00:00+00:00")
        assert after > before

    def test_access_boost_capped(self):
        p = RetentionPolicy(MemoryTier.SEMANTIC, half_life_days=10.0, max_access_boosts=3)
        item = MemoryItem(
            "i1",
            MemoryTier.SEMANTIC,
            "x",
            salience=1.0,
            created_at="2024-01-01T00:00:00+00:00",
        )
        for _ in range(10):
            p.record_access(item, "2024-01-01T00:00:00+00:00")
        assert int(item.metadata["access_boost_count"]) == 3


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

    def test_note_access_delays_decay(self):
        store = MemoryStore()
        boosted = MemoryItem(
            "b1",
            MemoryTier.EPISODIC,
            "boosted",
            salience=0.3,
            created_at="2024-01-01T00:00:00+00:00",
            last_accessed="2024-01-01T00:00:00+00:00",
        )
        unboosted = MemoryItem(
            "u1",
            MemoryTier.EPISODIC,
            "unboosted",
            salience=0.3,
            created_at="2024-01-01T00:00:00+00:00",
            last_accessed="2024-01-01T00:00:00+00:00",
        )
        store.add(boosted)
        store.add(unboosted)
        engine = DecayEngine()
        for day in range(20):
            engine.note_access(store, "b1", f"2024-01-{day + 1:02d}T00:00:00+00:00")
        engine.apply_decay(store, "2024-02-01T00:00:00+00:00")
        assert store.get("b1") is not None
        assert store.get("b1").tier == MemoryTier.EPISODIC
        boosted_tier = store.get("b1").tier
        unboosted_tier = store.get("u1").tier if store.get("u1") else MemoryTier.PROCEDURAL
        assert boosted_tier >= unboosted_tier

    def test_note_access_missing_item_returns_false(self):
        store = MemoryStore()
        engine = DecayEngine()
        assert not engine.note_access(store, "nope", "2024-01-01T00:00:00+00:00")

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


class TestLegalHolds:
    NOW = "2025-06-01T00:00:00+00:00"

    def _decaying_store(self) -> MemoryStore:
        # 5 days old with salience 0.1: decayed below the working-tier
        # floor (half-life 1d) but above the episodic floor (half-life
        # 14d), so one decay run demotes exactly one tier.
        store = MemoryStore()
        store.add(
            MemoryItem(
                "stale",
                MemoryTier.WORKING,
                "old scratch",
                salience=0.1,
                created_at="2025-05-27T00:00:00+00:00",
            )
        )
        return store

    def test_hold_protects_from_demotion(self):
        engine = DecayEngine()
        store = self._decaying_store()
        engine.place_hold("stale", reason="audit-2025")
        stats = engine.apply_decay(store, self.NOW)
        assert stats["protected_skipped"] == 1
        assert store._items["stale"].tier == MemoryTier.WORKING

    def test_release_makes_item_decay_again(self):
        engine = DecayEngine()
        store = self._decaying_store()
        engine.place_hold("stale")
        engine.apply_decay(store, self.NOW)
        assert engine.release_hold("stale") is True
        engine.apply_decay(store, self.NOW)
        assert store._items["stale"].tier == MemoryTier.EPISODIC

    def test_release_unknown_hold_returns_false(self):
        assert DecayEngine().release_hold("nope") is False

    def test_holds_listing_is_sorted_with_reasons(self):
        engine = DecayEngine()
        engine.place_hold("b2", reason="second")
        engine.place_hold("a1", reason="first")
        assert engine.holds() == {"a1": "first", "b2": "second"}
        assert engine.is_on_hold("a1")
        assert not engine.is_on_hold("z")

    def test_hold_protects_procedural_from_tombstone(self):
        engine = DecayEngine()
        store = MemoryStore()
        store.add(
            MemoryItem(
                "record",
                MemoryTier.PROCEDURAL,
                "compliance record",
                salience=0.0,
                created_at="2020-01-01T00:00:00+00:00",
            )
        )
        engine.place_hold("record", reason="legal")
        stats = engine.apply_decay(store, self.NOW)
        assert stats["tombstoned"] == 0
        assert "record" in store._items

    def test_hold_replaces_reason(self):
        engine = DecayEngine()
        engine.place_hold("x", reason="first")
        engine.place_hold("x", reason="second")
        assert engine.holds() == {"x": "second"}


class TestRetentionSnapshot:
    NOW = "2025-06-01T00:00:00+00:00"

    def _store(self) -> MemoryStore:
        store = MemoryStore()
        store.add(
            MemoryItem(
                "b_item",
                MemoryTier.EPISODIC,
                "ten day old episode",
                salience=0.8,
                created_at="2025-05-22T00:00:00+00:00",
            )
        )
        store.add(
            MemoryItem(
                "a_item",
                MemoryTier.WORKING,
                "pinned working note",
                salience=0.5,
                created_at="2025-05-31T00:00:00+00:00",
                pinned=True,
            )
        )
        return store

    def test_rows_sorted_and_typed(self):
        engine = DecayEngine()
        rows = engine.snapshot(self._store(), self.NOW)
        assert [row["item_id"] for row in rows] == ["a_item", "b_item"]
        assert rows[0]["tier"] == "working"
        assert rows[1]["tier"] == "episodic"

    def test_age_and_decay_are_quantized(self):
        engine = DecayEngine()
        rows = engine.snapshot(self._store(), self.NOW)
        b_row = rows[1]
        assert b_row["age_days"] == 10.0
        policy = DEFAULT_POLICIES[MemoryTier.EPISODIC]
        expected = 0.8 * policy.decay_factor(10.0)
        assert b_row["decayed_salience"] == round(expected, 6)

    def test_protection_flags(self):
        engine = DecayEngine()
        engine.place_hold("b_item", reason="audit")
        rows = engine.snapshot(self._store(), self.NOW)
        assert rows[0]["protected"] is True  # pinned
        assert rows[1]["protected"] is True  # held

    def test_state_reflects_grace_after_tombstone(self):
        engine = DecayEngine()
        store = MemoryStore()
        store.add(
            MemoryItem(
                "proc",
                MemoryTier.PROCEDURAL,
                "old procedure",
                salience=0.0,
                created_at="2020-01-01T00:00:00+00:00",
            )
        )
        engine.apply_decay(store, self.NOW)
        rows = engine.snapshot(store, self.NOW)
        assert rows[0]["state"] == "grace"

    def test_snapshot_is_deterministic(self):
        engine = DecayEngine()
        assert engine.snapshot(self._store(), self.NOW) == engine.snapshot(self._store(), self.NOW)

    def test_empty_store_snapshot(self):
        assert DecayEngine().snapshot(MemoryStore(), self.NOW) == []


class TestDecaySimulation:
    START = "2025-01-01T00:00:00+00:00"

    def _aging_store(self) -> MemoryStore:
        store = MemoryStore()
        # low-salience working item: should demote quickly (working half-life 1d)
        store.add(
            MemoryItem("w", MemoryTier.WORKING, "scratch", salience=0.05, created_at=self.START)
        )
        # protected item: should never move
        store.add(
            MemoryItem(
                "p", MemoryTier.WORKING, "held", salience=0.05, created_at=self.START, pinned=True
            )
        )
        return store

    def test_simulate_produces_one_row_per_day(self):
        engine = DecayEngine()
        results = engine.simulate(self._aging_store(), self.START, days=10)
        assert len(results) == 10
        assert [r["day"] for r in results] == list(range(10))

    def test_unprotected_item_demotes_over_time(self):
        engine = DecayEngine()
        store = self._aging_store()
        engine.simulate(store, self.START, days=10)
        assert store._items["w"].tier != MemoryTier.WORKING

    def test_protected_item_never_moves(self):
        engine = DecayEngine()
        store = self._aging_store()
        engine.simulate(store, self.START, days=30)
        assert store._items["p"].tier == MemoryTier.WORKING

    def test_total_items_never_increases(self):
        engine = DecayEngine()
        results = engine.simulate(self._aging_store(), self.START, days=20)
        totals = [r["total_items"] for r in results]
        assert all(later <= earlier for earlier, later in zip(totals, totals[1:], strict=False))

    def test_invalid_start_returns_empty(self):
        assert DecayEngine().simulate(self._aging_store(), "not-a-date", days=5) == []

    def test_procedural_item_reaches_tombstone_then_purge(self):
        engine = DecayEngine()
        store = MemoryStore()
        store.add(
            MemoryItem(
                "proc",
                MemoryTier.PROCEDURAL,
                "old",
                salience=0.0,
                created_at="2020-01-01T00:00:00+00:00",
            )
        )
        # grace for procedural is 14 days; simulate past it
        engine.apply_decay(store, self.START)  # ACTIVE -> GRACE
        assert "proc" in store._items
        results = engine.simulate(store, self.START, days=20)
        purged = [r for r in results if r["purged"] > 0]
        assert purged, "procedural item should eventually purge"
        assert "proc" not in store._items

    def test_simulation_is_deterministic(self):
        first = DecayEngine().simulate(self._aging_store(), self.START, days=15)
        second = DecayEngine().simulate(self._aging_store(), self.START, days=15)
        assert first == second

    def test_property_holds_across_whole_simulation(self):
        engine = DecayEngine()
        store = self._aging_store()
        assert engine.property_protected_never_deleted(store, "2025-02-01T00:00:00+00:00")
