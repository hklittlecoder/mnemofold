"""Access-boost caps, half-life math, and min_salience thresholds."""

import pytest

from mnemofold.decay import DecayEngine, RetentionPolicy
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier

NOW = "2026-06-01T00:00:00+00:00"
OLD = "2026-05-01T00:00:00+00:00"  # 31 days before NOW


def make_item(salience: float = 0.5) -> MemoryItem:
    return MemoryItem(
        item_id="m1",
        tier=MemoryTier.EPISODIC,
        content="x",
        salience=salience,
        created_at=OLD,
        last_accessed=OLD,
    )


class TestAccessBoosts:
    def test_boost_count_caps_at_max(self):
        store = MemoryStore()
        store.add(make_item())
        engine = DecayEngine()
        for i in range(10):
            engine.note_access(store, "m1", f"2026-05-{i + 2:02d}T00:00:00+00:00")
        item = store.peek("m1")
        assert item.metadata["access_boost_count"] == 4  # default cap

    def test_boosts_extend_effective_half_life(self):
        policy = RetentionPolicy(MemoryTier.EPISODIC, half_life_days=14.0)
        plain = make_item(salience=0.5)
        boosted = make_item(salience=0.5)
        boosted.metadata["access_boost_count"] = 4
        assert policy.decayed_salience(boosted, NOW) > policy.decayed_salience(plain, NOW)

    def test_unknown_item_note_access_is_false(self):
        assert not DecayEngine().note_access(MemoryStore(), "ghost", NOW)


class TestPolicyThresholds:
    def test_half_life_halves_salience(self):
        policy = RetentionPolicy(MemoryTier.EPISODIC, half_life_days=31.0)
        assert policy.decayed_salience(make_item(0.8), NOW) == pytest.approx(0.4, abs=1e-6)

    def test_min_salience_one_decays_everything_unpinned(self):
        policy = RetentionPolicy(MemoryTier.EPISODIC, min_salience=1.0)
        assert policy.should_decay(make_item(0.99), NOW)

    def test_min_salience_zero_keeps_fresh_items(self):
        policy = RetentionPolicy(MemoryTier.EPISODIC, min_salience=0.0, max_age_days=365.0)
        assert not policy.should_decay(make_item(0.01), NOW)

    def test_max_age_triggers_regardless_of_salience(self):
        policy = RetentionPolicy(MemoryTier.EPISODIC, max_age_days=30.0)
        assert policy.should_decay(make_item(0.99), NOW)  # 31 days old

    def test_custom_policy_via_engine(self):
        store = MemoryStore()
        store.add(make_item(0.9))
        engine = DecayEngine(
            policies={
                MemoryTier.EPISODIC: RetentionPolicy(MemoryTier.EPISODIC, max_age_days=30.0),
                **{
                    tier: policy
                    for tier, policy in DecayEngine().policies.items()
                    if tier != MemoryTier.EPISODIC
                },
            }
        )
        stats = engine.apply_decay(store, NOW)
        assert stats["demoted"] == 1
        assert store.peek("m1").tier == MemoryTier.SEMANTIC
