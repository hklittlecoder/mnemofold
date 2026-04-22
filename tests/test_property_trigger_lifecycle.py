"""Randomized lifecycles: derived rules only ever cover active commitments.

For seeded ledgers with random completions/cancellations over 15 days:
the engine's rule set must equal the active commitment set at every
tick, and no fired trigger may target a terminal commitment.
"""

import random
from datetime import UTC, datetime, timedelta

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus
from mnemofold.triggers import TriggerEngine, derive_commitment_rules

START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
ACTIVE = {CommitmentStatus.OPEN, CommitmentStatus.IN_PROGRESS}


def build_ledger(seed: int) -> CommitmentLedger:
    rng = random.Random(seed)
    ledger = CommitmentLedger()
    for i in range(10):
        due = START + timedelta(days=rng.randint(-2, 12))
        ledger.add(
            Commitment(
                commitment_id=f"c{i}",
                owed_by=f"p{rng.randint(1, 3)}",
                owed_to=f"p{rng.randint(1, 3)}",
                description=f"task {i}",
                due_date=due.isoformat(),
                created_at=(START - timedelta(days=1)).isoformat(),
            )
        )
    return ledger


class TestTriggerLifecycleProperties:
    def test_rules_track_active_set_and_no_ghosts_fire(self):
        for seed in range(8):
            rng = random.Random(seed + 100)
            ledger = build_ledger(seed)
            engine = TriggerEngine()
            for day in range(15):
                now = START + timedelta(days=day)
                engine.replace_rules(derive_commitment_rules(ledger, now))
                fired = engine.tick(now)
                active = {c.commitment_id for c in ledger.all_commitments() if c.status in ACTIVE}
                assert {r.rule_id for r in engine.rules()} == {f"trg-{cid}" for cid in active}, (
                    seed,
                    day,
                )
                assert all(f.target_id in active for f in fired), (seed, day)
                candidates = sorted(active)
                if candidates and rng.random() < 0.3:
                    ledger.transition(
                        rng.choice(candidates),
                        rng.choice([CommitmentStatus.DONE, CommitmentStatus.CANCELLED]),
                        now.isoformat(),
                    )

    def test_append_only_engine_would_leak_ghosts(self):
        # control: the pre-fix append-only behavior fires for a finished
        # commitment, which is exactly what replace_rules prevents
        ledger = build_ledger(3)
        engine = TriggerEngine()
        engine.add_rule(derive_commitment_rules(ledger, START)[0])
        ghost = engine.rules()[0].target_id
        ledger.transition(ghost, CommitmentStatus.DONE, START.isoformat())
        fired = engine.tick(START + timedelta(hours=13))
        assert any(f.target_id == ghost for f in fired)
