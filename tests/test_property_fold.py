"""Property tests for folding and temporal as-of guarantees.

Folding must be idempotent — a second nightly pass over the same store
changes nothing — and as-of answers must be stable: facts learned later
never rewrite what was known on an earlier date. Both properties are
checked over seeded random stores, not just hand-picked examples. These
are structural invariants of the machinery, not quality claims about any
corpus.
"""

from __future__ import annotations

import random

import pytest

from mnemofold.fold import Folder, fold_idempotent_check
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.temporal import IntervalFact, TemporalStore

FOLD_TS = "2025-03-01T02:00:00+00:00"
PHRASES = (
    "release plan reviewed with the core team",
    "release plan reviewed with the core team today",
    "budget report sent to finance",
    "budget report sent to the finance group",
    "design sync moved to thursday",
    "risk register updated for launch",
    "completely unrelated standup note about weather",
)


def _random_store(rng: random.Random, n: int) -> MemoryStore:
    store = MemoryStore()
    for i in range(n):
        store.add(
            MemoryItem(
                item_id=f"ep{i:03d}",
                tier=MemoryTier.EPISODIC,
                content=rng.choice(PHRASES),
                title=f"episode {i}",
                salience=round(rng.uniform(0.0, 1.0), 3),
                access_count=rng.randint(0, 5),
                created_at=f"2025-02-{rng.randint(1, 28):02d}T09:00:00+00:00",
            )
        )
    return store


class TestFoldIdempotence:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_second_fold_changes_nothing(self, seed):
        rng = random.Random(seed)
        store = _random_store(rng, 20)
        folder = Folder(similarity_threshold=0.7)
        first = folder.fold(store, FOLD_TS, fold_id="f1")
        after_first = store.total_count()
        second = folder.fold(store, FOLD_TS, fold_id="f2")
        assert second.merges == []
        assert second.new_semantic == []
        assert store.total_count() == after_first == second.items_after
        assert first.items_before == 20

    @pytest.mark.parametrize("seed", [1, 2])
    def test_helper_agrees_with_manual_double_fold(self, seed):
        rng = random.Random(seed + 50)
        store = _random_store(rng, 16)
        assert fold_idempotent_check(store, Folder(similarity_threshold=0.7), FOLD_TS)

    def test_same_seed_folds_to_the_same_report_digest(self):
        first = _random_store(random.Random(7), 18)
        second = _random_store(random.Random(7), 18)
        folder = Folder(similarity_threshold=0.7)
        r1 = folder.fold(first, FOLD_TS, fold_id="same")
        r2 = folder.fold(second, FOLD_TS, fold_id="same")
        assert r1.digest() == r2.digest()


class TestAsOfStability:
    def _timeline(self) -> TemporalStore[str]:
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact("owner", "alice", "2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00")
        )
        store.add(IntervalFact("owner", "bob", "2025-02-01T00:00:00+00:00"))
        return store

    def test_later_facts_never_rewrite_earlier_answers(self):
        store = self._timeline()
        january = store.as_of("owner", "2025-01-15T00:00:00+00:00")
        february = store.as_of("owner", "2025-02-15T00:00:00+00:00")
        assert january is not None and february is not None
        assert january.value == "alice"
        # Later consolidation: bob is superseded in March, new keys appear.
        current = store.current("owner")
        assert current is not None
        current.valid_to = "2025-03-01T00:00:00+00:00"
        store.add(IntervalFact("owner", "carol", "2025-03-01T00:00:00+00:00"))
        store.add(IntervalFact("budget", "900k", "2025-02-20T00:00:00+00:00"))
        again_jan = store.as_of("owner", "2025-01-15T00:00:00+00:00")
        again_feb = store.as_of("owner", "2025-02-15T00:00:00+00:00")
        assert again_jan is not None and again_feb is not None
        assert again_jan.value == january.value
        assert again_feb.value == february.value
        march = store.as_of("owner", "2025-03-15T00:00:00+00:00")
        assert march is not None and march.value == "carol"

    def test_as_of_outside_validity_returns_none(self):
        store = self._timeline()
        assert store.as_of("owner", "2024-12-31T23:59:59+00:00") is None
        assert store.as_of("unknown", "2025-01-15T00:00:00+00:00") is None

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_appending_history_preserves_all_earlier_answers(self, seed):
        rng = random.Random(seed)
        store: TemporalStore[int] = TemporalStore()
        starts: list[str] = []
        for version in range(5):
            start = f"2025-01-{version * 5 + 1:02d}T00:00:00+00:00"
            end = f"2025-01-{version * 5 + 6:02d}T00:00:00+00:00" if version < 4 else None
            store.add(IntervalFact("counter", version, start, end))
            starts.append(start)
        snapshot = {day: store.as_of("counter", day) for day in starts}
        assert all(fact is not None for fact in snapshot.values())
        for extra in range(3):
            store.add(
                IntervalFact(f"extra-{extra}", rng.randint(0, 9), "2025-06-01T00:00:00+00:00")
            )
        for day, fact in snapshot.items():
            answer = store.as_of("counter", day)
            assert answer is not None
            assert fact is not None
            assert answer.value == fact.value
