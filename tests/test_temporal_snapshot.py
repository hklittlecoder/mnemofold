"""Bulk as-of snapshots must agree with per-key as_of queries."""

from mnemofold.temporal import IntervalFact, TemporalStore


def make_store() -> TemporalStore[str]:
    store: TemporalStore[str] = TemporalStore()
    store.add(IntervalFact(fact_key="owner", value="ana", valid_from="2026-01-05T09:00:00+00:00"))
    store.supersede("owner", "bo", "2026-02-10T09:00:00+00:00")
    store.add(
        IntervalFact(
            fact_key="due",
            value="2026-03-01",
            valid_from="2026-01-06T09:00:00+00:00",
            valid_to="2026-02-20T09:00:00+00:00",
        )
    )
    store.add(IntervalFact(fact_key="room", value="B2", valid_from="2026-03-01T09:00:00+00:00"))
    return store


class TestSnapshotAt:
    def test_snapshot_matches_per_key_as_of(self):
        store = make_store()
        for when in (
            "2026-01-10T00:00:00+00:00",
            "2026-02-15T00:00:00+00:00",
            "2026-03-05T00:00:00+00:00",
        ):
            snapshot = store.snapshot_at(when)
            for key, fact in snapshot.items():
                assert fact is store.as_of(key, when), (when, key)

    def test_keys_absent_before_their_start(self):
        snapshot = make_store().snapshot_at("2026-01-01T00:00:00+00:00")
        assert snapshot == {}

    def test_closed_facts_drop_out(self):
        snapshot = make_store().snapshot_at("2026-02-25T00:00:00+00:00")
        assert set(snapshot) == {"owner"}  # due closed 02-20, room starts 03-01

    def test_snapshot_keys_are_sorted(self):
        snapshot = make_store().snapshot_at("2026-03-05T00:00:00+00:00")
        assert list(snapshot) == sorted(snapshot)
        assert set(snapshot) == {"owner", "room"}  # due closed on 02-20

    def test_snapshot_values_after_supersede(self):
        store = make_store()
        before = store.snapshot_at("2026-01-10T00:00:00+00:00")
        store.supersede("owner", "cy", "2026-04-01T09:00:00+00:00")
        after = store.snapshot_at("2026-01-10T00:00:00+00:00")
        assert before["owner"].value == "ana"
        assert after["owner"].value == "ana"  # earlier instant is stable
        assert store.snapshot_at("2026-04-02T00:00:00+00:00")["owner"].value == "cy"
