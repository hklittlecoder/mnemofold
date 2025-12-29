"""As-of answers must stay stable as later supersedes land.

A snapshot taken for instant D may never change because of writes that
happen "after" D — this is the temporal contract consolidation and
conflict resolution rely on.
"""

from mnemofold.temporal import IntervalValidator, TemporalStore

BASE = "2026-01-01T00:00:00+00:00"


def iso(day: int) -> str:
    return f"2026-01-{day:02d}T00:00:00+00:00"


class TestAsOfStability:
    def test_answers_freeze_as_history_grows(self):
        store: TemporalStore[str] = TemporalStore()
        store.supersede("status", "draft", iso(1))
        probes = {iso(5): store.as_of("status", iso(5)).value}
        for day, value in ((10, "review"), (15, "final"), (20, "archived")):
            store.supersede("status", value, iso(day))
            # every earlier probe must keep its answer
            for when, expected in probes.items():
                assert store.as_of("status", when).value == expected
            probes[iso(day + 2)] = store.as_of("status", iso(day + 2)).value
        assert probes[iso(5)] == "draft"
        assert probes[iso(12)] == "review"
        assert probes[iso(17)] == "final"
        assert store.as_of("status", iso(25)).value == "archived"

    def test_snapshots_taken_earlier_stay_valid(self):
        store: TemporalStore[str] = TemporalStore()
        store.supersede("a", "1", iso(1))
        store.supersede("b", "x", iso(2))
        early = {k: f.value for k, f in store.snapshot_at(iso(3)).items()}
        store.supersede("a", "2", iso(10))
        store.supersede("c", "new", iso(11))
        again = {k: f.value for k, f in store.snapshot_at(iso(3)).items()}
        assert early == again == {"a": "1", "b": "x"}

    def test_closed_fact_objects_are_not_mutated_again(self):
        store: TemporalStore[str] = TemporalStore()
        first = store.supersede("k", "v1", iso(1))
        store.supersede("k", "v2", iso(5))
        closed_at = first.valid_to
        store.supersede("k", "v3", iso(9))
        assert first.valid_to == closed_at == iso(5)

    def test_supersede_chain_is_validator_clean(self):
        store: TemporalStore[str] = TemporalStore()
        for day in range(1, 12):
            store.supersede("k", f"v{day}", iso(day))
        assert IntervalValidator().validate(store) == []
        assert store.superseded_count() == 10

    def test_interleaved_keys_do_not_interfere(self):
        store: TemporalStore[str] = TemporalStore()
        store.supersede("x", "1", iso(1))
        store.supersede("y", "1", iso(1))
        store.supersede("x", "2", iso(4))
        store.supersede("y", "2", iso(7))
        snap = store.snapshot_at(iso(5))
        assert snap["x"].value == "2"
        assert snap["y"].value == "1"
        assert IntervalValidator().validate(store) == []
