"""Tests for the memory tiers module."""

from __future__ import annotations

from mnemofold.memory import (
    MemoryItem,
    MemoryStore,
    MemoryTier,
    TierPolicy,
)


class TestMemoryTier:
    def test_tier_order(self):
        tiers = list(MemoryTier)
        assert MemoryTier.WORKING in tiers
        assert MemoryTier.EPISODIC in tiers
        assert MemoryTier.SEMANTIC in tiers
        assert MemoryTier.PROCEDURAL in tiers


class TestMemoryItem:
    def test_tier_from_string(self):
        item = MemoryItem("i1", "working", "content")
        assert item.tier == MemoryTier.WORKING

    def test_default_values(self):
        item = MemoryItem("i1", MemoryTier.EPISODIC, "content")
        assert item.salience == 0.0
        assert item.access_count == 0
        assert item.pinned is False
        assert item.tags == set()


class TestMemoryStore:
    def test_add_and_get(self):
        store = MemoryStore()
        item = MemoryItem("i1", MemoryTier.SEMANTIC, "test content", title="Test")
        store.add(item)
        result = store.get("i1")
        assert result is not None
        assert result.title == "Test"
        assert result.access_count == 1  # counted by get

    def test_get_nonexistent(self):
        store = MemoryStore()
        assert store.get("nope") is None

    def test_remove(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.SEMANTIC, "x"))
        store.remove("i1")
        assert store.get("i1") is None

    def test_promote_from_episodic_to_working(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.EPISODIC, "x"))
        assert store.promote("i1") is True
        assert store.get("i1").tier == MemoryTier.WORKING

    def test_promote_already_working(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.WORKING, "x"))
        assert store.promote("i1") is False

    def test_promote_from_semantic_to_episodic(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.SEMANTIC, "x"))
        assert store.promote("i1") is True
        assert store.get("i1").tier == MemoryTier.EPISODIC

    def test_demote_from_working_to_episodic(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.WORKING, "x"))
        assert store.demote("i1") is True
        assert store.get("i1").tier == MemoryTier.EPISODIC

    def test_demote_pinned_item_fails(self):
        store = MemoryStore()
        item = MemoryItem("i1", MemoryTier.WORKING, "x", pinned=True)
        store.add(item)
        assert store.demote("i1") is False
        assert store.get("i1").tier == MemoryTier.WORKING

    def test_demote_from_procedural_fails(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.PROCEDURAL, "x"))
        assert store.demote("i1") is False

    def test_promote_nonexistent_fails(self):
        store = MemoryStore()
        assert store.promote("nope") is False

    def test_items_by_tier(self):
        store = MemoryStore()
        store.add(MemoryItem("a", MemoryTier.WORKING, "1"))
        store.add(MemoryItem("b", MemoryTier.WORKING, "2"))
        store.add(MemoryItem("c", MemoryTier.SEMANTIC, "3"))
        assert len(store.items_by_tier(MemoryTier.WORKING)) == 2
        assert len(store.items_by_tier(MemoryTier.SEMANTIC)) == 1
        assert len(store.items_by_tier(MemoryTier.EPISODIC)) == 0

    def test_working_set_size_bound(self):
        store = MemoryStore(working_set_size=5)
        for i in range(10):
            item = MemoryItem(f"i{i}", MemoryTier.WORKING, f"content {i}")
            item.salience = float(i) / 10.0
            store.add(item)
        working = store.items_by_tier(MemoryTier.WORKING)
        assert len(working) == 5
        # Top 5 salience items (0.5 to 0.9) should remain
        saliences = sorted(i.salience for i in working)
        assert saliences[0] >= 0.5

    def test_working_set_pinned_not_evicted(self):
        store = MemoryStore(working_set_size=2)
        a = MemoryItem("a", MemoryTier.WORKING, "a")
        a.salience = 0.1
        a.pinned = True
        b = MemoryItem("b", MemoryTier.WORKING, "b")
        b.salience = 0.5
        c = MemoryItem("c", MemoryTier.WORKING, "c")
        c.salience = 0.9
        store.add(a)
        store.add(b)
        store.add(c)
        # 'a' is pinned and low-salience, 'b' has middle salience
        # Expected: c (0.9) + a (pinned) stay, b is evicted
        working = store.working_set()
        assert len(working) == 2
        assert any(i.item_id == "a" for i in working)
        assert any(i.item_id == "c" for i in working)

    def test_tier_counts(self):
        store = MemoryStore()
        store.add(MemoryItem("a", MemoryTier.WORKING, "1"))
        store.add(MemoryItem("b", MemoryTier.EPISODIC, "2"))
        store.add(MemoryItem("c", MemoryTier.SEMANTIC, "3"))
        store.add(MemoryItem("d", MemoryTier.PROCEDURAL, "4"))
        counts = store.tier_counts()
        assert counts[MemoryTier.WORKING] == 1
        assert counts[MemoryTier.EPISODIC] == 1
        assert counts[MemoryTier.SEMANTIC] == 1
        assert counts[MemoryTier.PROCEDURAL] == 1

    def test_search_by_tag(self):
        store = MemoryStore()
        a = MemoryItem("a", MemoryTier.SEMANTIC, "1", tags={"important", "work"})
        b = MemoryItem("b", MemoryTier.SEMANTIC, "2", tags={"personal"})
        store.add(a)
        store.add(b)
        result = store.search_by_tag("important")
        assert len(result) == 1
        assert result[0].item_id == "a"

    def test_total_count(self):
        store = MemoryStore()
        store.add(MemoryItem("a", MemoryTier.WORKING, "1"))
        store.add(MemoryItem("b", MemoryTier.SEMANTIC, "2"))
        store.add(MemoryItem("c", MemoryTier.EPISODIC, "3"))
        assert store.total_count() == 3


class TestAccessRecording:
    def test_record_access_updates_count_and_timestamp(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.EPISODIC, "c"))
        assert store.record_access("i1", "2025-03-10T09:00:00+00:00") is True
        item = store._items["i1"]
        assert item.access_count == 1
        assert item.last_accessed == "2025-03-10T09:00:00+00:00"

    def test_record_access_accumulates(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.EPISODIC, "c"))
        store.record_access("i1", "2025-03-10T09:00:00+00:00")
        store.record_access("i1", "2025-03-11T09:00:00+00:00")
        item = store._items["i1"]
        assert item.access_count == 2
        assert item.last_accessed == "2025-03-11T09:00:00+00:00"

    def test_record_access_unknown_item(self):
        assert MemoryStore().record_access("nope", "2025-03-10T09:00:00+00:00") is False


class TestRetention:
    def _store_with(self, retain_until: str) -> MemoryStore:
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.EPISODIC, "c", retain_until=retain_until))
        return store

    def test_inside_window_is_protected(self):
        store = self._store_with("2025-06-01T00:00:00+00:00")
        assert store.under_retention("i1", "2025-05-31T23:59:59+00:00") is True

    def test_boundary_is_exclusive(self):
        store = self._store_with("2025-06-01T00:00:00+00:00")
        assert store.under_retention("i1", "2025-06-01T00:00:00+00:00") is False

    def test_after_window_is_not_protected(self):
        store = self._store_with("2025-06-01T00:00:00+00:00")
        assert store.under_retention("i1", "2025-06-02T00:00:00+00:00") is False

    def test_mixed_offsets_compare_as_instants(self):
        store = self._store_with("2025-06-01T00:00:00+00:00")
        # 2025-06-01 07:00 +08:00 == 2025-05-31 23:00 UTC -> still inside
        assert store.under_retention("i1", "2025-06-01T07:00:00+08:00") is True

    def test_no_hold_means_no_protection(self):
        store = MemoryStore()
        store.add(MemoryItem("i1", MemoryTier.EPISODIC, "c"))
        assert store.under_retention("i1", "2025-01-01T00:00:00+00:00") is False

    def test_unknown_item_or_bad_timestamps(self):
        store = self._store_with("2025-06-01T00:00:00+00:00")
        assert store.under_retention("nope", "2025-01-01T00:00:00+00:00") is False
        assert store.under_retention("i1", "garbage") is False


class TestTierPolicy:
    NOW = "2025-06-01T00:00:00+00:00"

    def _store(self) -> MemoryStore:
        return MemoryStore(working_set_size=10)

    def _item(self, item_id, tier=MemoryTier.EPISODIC, **kwargs) -> MemoryItem:
        return MemoryItem(item_id, tier, "content", **kwargs)

    def test_promotion_requires_salience_and_accesses(self):
        store = self._store()
        store.add(self._item("hot", salience=0.8, access_count=3))
        store.add(self._item("cold", salience=0.8, access_count=2))
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.promoted == ["hot"]
        # promotion moves one tier up the ladder: episodic -> working
        assert store._items["hot"].tier == MemoryTier.WORKING
        assert store._items["cold"].tier == MemoryTier.EPISODIC

    def test_working_tier_is_the_ceiling(self):
        store = self._store()
        store.add(self._item("top", tier=MemoryTier.WORKING, salience=0.9, access_count=9))
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.promoted == []
        assert store._items["top"].tier == MemoryTier.WORKING

    def test_demotion_on_staleness_and_low_salience(self):
        store = self._store()
        store.add(
            self._item(
                "old",
                salience=0.1,
                last_accessed="2025-01-01T00:00:00+00:00",
            )
        )
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.demoted == ["old"]
        # demotion moves one tier down the ladder, not straight to the floor
        assert store._items["old"].tier == MemoryTier.SEMANTIC

    def test_recent_or_salient_items_are_kept(self):
        store = self._store()
        store.add(self._item("recent", salience=0.1, last_accessed="2025-05-30T00:00:00+00:00"))
        store.add(self._item("salient", salience=0.5, last_accessed="2025-01-01T00:00:00+00:00"))
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.demoted == []

    def test_pinned_items_are_protected(self):
        store = self._store()
        store.add(
            self._item(
                "pinned", salience=0.0, last_accessed="2025-01-01T00:00:00+00:00", pinned=True
            )
        )
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.demoted == []
        assert report.protected == ["pinned"]
        assert store._items["pinned"].tier == MemoryTier.EPISODIC

    def test_retention_hold_protects(self):
        store = self._store()
        store.add(
            self._item(
                "held",
                salience=0.0,
                last_accessed="2025-01-01T00:00:00+00:00",
                retain_until="2025-12-31T00:00:00+00:00",
            )
        )
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.protected == ["held"]
        assert store._items["held"].tier == MemoryTier.EPISODIC

    def test_procedural_is_the_floor(self):
        store = self._store()
        store.add(
            self._item(
                "bottom",
                tier=MemoryTier.PROCEDURAL,
                salience=0.0,
                last_accessed="2025-01-01T00:00:00+00:00",
            )
        )
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.demoted == []
        assert report.protected == []

    def test_promotion_wins_over_demotion(self):
        store = self._store()
        store.add(
            self._item(
                "both", salience=0.75, access_count=5, last_accessed="2024-01-01T00:00:00+00:00"
            )
        )
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.promoted == ["both"]
        assert report.demoted == []

    def test_report_ids_are_sorted(self):
        store = self._store()
        for name in ("z", "a", "m"):
            store.add(self._item(name, salience=0.9, access_count=3))
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.promoted == ["a", "m", "z"]

    def test_invalid_now_raises(self):
        import pytest

        with pytest.raises(ValueError, match="invalid policy timestamp"):
            self._store().apply_policy(TierPolicy(), "not-a-time")

    def test_created_at_fallback_for_demotion_age(self):
        store = self._store()
        store.add(self._item("noaccess", salience=0.1, created_at="2025-01-01T00:00:00+00:00"))
        report = store.apply_policy(TierPolicy(), self.NOW)
        assert report.demoted == ["noaccess"]
