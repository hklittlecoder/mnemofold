"""Retention hold extension and release on the memory store."""

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier, TierPolicy

NOW = "2026-03-01T00:00:00+00:00"


def make_store(item_id: str = "m1") -> MemoryStore:
    store = MemoryStore()
    store.add(
        MemoryItem(
            item_id=item_id,
            tier=MemoryTier.EPISODIC,
            content="release note",
            salience=0.1,
            created_at="2026-01-01T00:00:00+00:00",
            last_accessed="2026-01-01T00:00:00+00:00",
        )
    )
    return store


class TestExtendRetention:
    def test_extend_sets_hold(self):
        store = make_store()
        assert store.extend_retention("m1", "2026-04-01T00:00:00+00:00", reason="legal")
        assert store.peek("m1").retain_until == "2026-04-01T00:00:00+00:00"
        assert store.under_retention("m1", NOW)

    def test_extend_rejects_unparseable_instant(self):
        store = make_store()
        assert not store.extend_retention("m1", "not-a-date")
        assert store.peek("m1").retain_until == ""
        assert store.retention_history("m1") == []

    def test_extend_unknown_item_returns_false(self):
        assert not make_store().extend_retention("ghost", "2026-04-01T00:00:00+00:00")

    def test_history_records_previous_hold(self):
        store = make_store()
        store.extend_retention("m1", "2026-04-01T00:00:00+00:00", reason="audit")
        store.extend_retention("m1", "2026-05-01T00:00:00+00:00", reason="extended")
        history = store.retention_history("m1")
        assert history[0] == {
            "previous": "",
            "until": "2026-04-01T00:00:00+00:00",
            "reason": "audit",
        }
        assert history[1]["previous"] == "2026-04-01T00:00:00+00:00"

    def test_shortening_a_hold_is_allowed_and_recorded(self):
        store = make_store()
        store.extend_retention("m1", "2026-06-01T00:00:00+00:00")
        assert store.extend_retention("m1", "2026-03-15T00:00:00+00:00", reason="released early")
        assert store.peek("m1").retain_until == "2026-03-15T00:00:00+00:00"
        assert len(store.retention_history("m1")) == 2

    def test_clear_removes_hold_and_keeps_history(self):
        store = make_store()
        store.extend_retention("m1", "2026-04-01T00:00:00+00:00")
        assert store.clear_retention("m1", reason="hold lifted")
        assert store.peek("m1").retain_until == ""
        assert not store.under_retention("m1", NOW)
        assert store.retention_history("m1")[-1] == {
            "previous": "2026-04-01T00:00:00+00:00",
            "until": "",
            "reason": "hold lifted",
        }

    def test_clear_without_hold_is_a_noop(self):
        store = make_store()
        assert not store.clear_retention("m1")
        assert not store.clear_retention("ghost")

    def test_retention_history_unknown_item_is_empty(self):
        assert make_store().retention_history("ghost") == []

    def test_hold_blocks_policy_demotion(self):
        policy = TierPolicy(demote_after_days=30.0, demote_below_salience=0.3)

        plain = make_store()
        plain.apply_policy(policy, NOW)
        assert plain.peek("m1").tier != MemoryTier.EPISODIC  # control: it does demote

        held = make_store()
        held.extend_retention("m1", "2026-04-01T00:00:00+00:00", reason="legal hold")
        held.apply_policy(policy, NOW)
        assert held.peek("m1").tier == MemoryTier.EPISODIC
