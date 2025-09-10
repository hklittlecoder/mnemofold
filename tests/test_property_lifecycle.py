"""Lifecycle property tests: decay protection and ledger transitions.

Decay may lower salience and eventually remove unprotected ephemera,
but it must never delete pinned items, legal-hold tags, or hold-listed
records — checked over seeded random stores across long simulations.
Ledger transitions must match the declared table in both directions:
every allowed move succeeds, every forbidden move is refused without
touching state, and terminal statuses are final.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.decay import DecayEngine
from mnemofold.ledger import VALID_TRANSITIONS, Commitment, CommitmentLedger, CommitmentStatus
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier

START = datetime(2025, 1, 1, tzinfo=UTC)
TIERS = [MemoryTier.WORKING, MemoryTier.EPISODIC, MemoryTier.SEMANTIC, MemoryTier.PROCEDURAL]
KINDS = ["pinned", "held", "tagged", "plain", "plain"]


def _random_store(rng: random.Random, n: int) -> tuple[MemoryStore, dict[str, str]]:
    """Store with a random mix of protected and ordinary low-salience items."""
    store = MemoryStore()
    kinds: dict[str, str] = {}
    for i in range(n):
        kind = rng.choice(KINDS)
        created = START - timedelta(days=rng.randint(30, 500))
        item = MemoryItem(
            item_id=f"m{i:03d}",
            tier=rng.choice(TIERS),
            content=f"fleeting note {i}",
            salience=round(rng.uniform(0.0, 0.2), 3),
            created_at=created.isoformat(),
            pinned=kind == "pinned",
            tags={"legal_hold"} if kind == "tagged" else set(),
        )
        store.add(item)
        kinds[item.item_id] = kind
    return store, kinds


def _engine_with_holds(kinds: dict[str, str]) -> DecayEngine:
    engine = DecayEngine()
    for item_id, kind in sorted(kinds.items()):
        if kind == "held":
            engine.place_hold(item_id, reason="quarterly audit")
    return engine


class TestDecayProtectionProperty:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_protected_records_survive_a_long_simulation(self, seed):
        rng = random.Random(seed)
        store, kinds = _random_store(rng, 24)
        engine = _engine_with_holds(kinds)
        protected = sorted(i for i, k in kinds.items() if k in {"pinned", "held", "tagged"})
        assert protected, "random store must contain protected items"
        for day in range(1, 61):
            now = (START + timedelta(days=day)).isoformat()
            engine.apply_decay(store, now)
            for item_id in protected:
                assert store.peek(item_id) is not None, f"{item_id} deleted on day {day}"
        final = (START + timedelta(days=60)).isoformat()
        assert engine.property_protected_never_deleted(store, final)

    @pytest.mark.parametrize("seed", [1, 2])
    def test_unprotected_low_salience_items_do_decay_away(self, seed):
        rng = random.Random(seed + 40)
        store, kinds = _random_store(rng, 24)
        engine = _engine_with_holds(kinds)
        for day in range(1, 401):
            engine.apply_decay(store, (START + timedelta(days=day)).isoformat())
        plain = [i for i, k in kinds.items() if k == "plain"]
        removed = [i for i in plain if store.peek(i) is None]
        assert removed, "a 400-day sweep must remove at least some unprotected items"

    def test_released_hold_becomes_decayable_again(self):
        store = MemoryStore()
        item = MemoryItem(
            item_id="held",
            tier=MemoryTier.WORKING,
            content="scratch",
            salience=0.01,
            created_at=(START - timedelta(days=30)).isoformat(),
        )
        store.add(item)
        engine = DecayEngine()
        engine.place_hold("held", reason="audit")
        engine.apply_decay(store, (START + timedelta(days=10)).isoformat())
        assert store.peek("held") is not None
        assert engine.release_hold("held")
        # First unprotected pass demotes toward the bottom tier...
        engine.apply_decay(store, (START + timedelta(days=11)).isoformat())
        demoted = store.peek("held")
        assert demoted is not None
        assert demoted.tier != MemoryTier.WORKING
        # ...and the procedural grace period eventually purges it.
        for day in range(12, 40):
            engine.apply_decay(store, (START + timedelta(days=day)).isoformat())
        assert store.peek("held") is None


class TestLedgerTransitionProperty:
    def _ledger(self, n: int = 6) -> CommitmentLedger:
        ledger = CommitmentLedger()
        for i in range(n):
            ledger.add(
                Commitment(
                    commitment_id=f"c{i:02d}",
                    owed_by=f"p{i % 3}",
                    owed_to="team",
                    description=f"deliverable {i}",
                    due_date=(START + timedelta(days=i + 1)).isoformat(),
                    created_at=START.isoformat(),
                )
            )
        return ledger

    def test_transition_table_matches_can_transition_to(self):
        for status in CommitmentStatus:
            commitment = Commitment(
                "c", "a", "b", "task", "2025-01-10T00:00:00+00:00", status=status
            )
            for target in CommitmentStatus:
                assert commitment.can_transition_to(target) == (target in VALID_TRANSITIONS[status])

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_random_walks_never_leave_the_table(self, seed):
        rng = random.Random(seed)
        ledger = self._ledger()
        terminal = {
            CommitmentStatus.DONE,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.SUPERSEDED,
        }
        for step in range(50):
            cid = f"c{rng.randrange(6):02d}"
            target = rng.choice(list(CommitmentStatus))
            before = ledger.get(cid)
            assert before is not None
            status_before = before.status
            allowed = before.can_transition_to(target)
            ok = ledger.transition(cid, target, (START + timedelta(hours=step)).isoformat())
            assert ok == allowed
            after = ledger.get(cid)
            assert after is not None
            assert after.status == (target if ok else status_before)
            if ok and target in terminal:
                stamp = (START + timedelta(hours=step)).isoformat()
                for other in CommitmentStatus:
                    assert not ledger.transition(cid, other, stamp)

    def test_failed_transition_leaves_history_untouched(self):
        ledger = self._ledger(n=1)
        assert ledger.transition("c00", CommitmentStatus.DONE, "2025-01-02T00:00:00+00:00")
        history_len = len(ledger.transition_history())
        assert not ledger.transition("c00", CommitmentStatus.OPEN, "2025-01-03T00:00:00+00:00")
        got = ledger.get("c00")
        assert got is not None
        assert got.status == CommitmentStatus.DONE
        assert len(ledger.transition_history()) == history_len

    def test_open_to_in_progress_and_back_is_allowed(self):
        ledger = self._ledger(n=1)
        assert ledger.transition("c00", CommitmentStatus.IN_PROGRESS, "2025-01-02T00:00:00+00:00")
        assert ledger.transition("c00", CommitmentStatus.OPEN, "2025-01-03T00:00:00+00:00")
