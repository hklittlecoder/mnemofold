"""Randomized ledgers must keep aging and burndown invariants.

Seeded RNG only; every invariant holds across the whole sweep: aging
buckets partition the active set, burndown counters never decrease, and
resolved never exceeds created.
"""

import random
from datetime import UTC, datetime, timedelta

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

START = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
ACTIVE = {CommitmentStatus.OPEN, CommitmentStatus.IN_PROGRESS}
TERMINAL = {CommitmentStatus.DONE, CommitmentStatus.CANCELLED}


def build_ledger(seed: int) -> CommitmentLedger:
    rng = random.Random(seed)
    ledger = CommitmentLedger()
    for i in range(rng.randint(3, 15)):
        cid = f"c{i}"
        created = START + timedelta(days=rng.randint(0, 10), hours=rng.randint(0, 12))
        due = created + timedelta(days=rng.randint(-3, 20))
        ledger.add(
            Commitment(
                commitment_id=cid,
                owed_by=f"p{rng.randint(1, 4)}",
                owed_to=f"p{rng.randint(1, 4)}",
                description=f"task {cid}",
                due_date=due.isoformat(),
                created_at=created.isoformat(),
            )
        )
        if rng.random() < 0.4:
            done_at = created + timedelta(days=rng.randint(1, 12))
            status = rng.choice(sorted(TERMINAL, key=str))
            ledger.transition(cid, status, done_at.isoformat())
    return ledger


class TestLedgerProperties:
    def test_aging_buckets_partition_active_set(self):
        for seed in range(12):
            ledger = build_ledger(seed)
            report = ledger.aging_report((START + timedelta(days=14)).isoformat())
            all_ids = []
            for name in ("overdue", "due_today", "due_this_week", "later", "no_due"):
                all_ids.extend(report[name])
            assert len(all_ids) == len(set(all_ids)), seed
            assert report["total_active"] == len(all_ids), seed
            expected = sum(1 for c in ledger.all_commitments() if c.status in ACTIVE)
            assert report["total_active"] == expected, seed

    def test_burndown_counters_never_decrease(self):
        for seed in range(12):
            series = build_ledger(seed).burndown_series("2026-03-01", 25)
            created = [row["created"] for row in series]
            resolved = [row["resolved"] for row in series]
            assert created == sorted(created), seed
            assert resolved == sorted(resolved), seed

    def test_resolved_never_exceeds_created(self):
        for seed in range(12):
            for row in build_ledger(seed).burndown_series("2026-03-01", 25):
                assert row["resolved"] <= row["created"], (seed, row["day"])

    def test_final_created_counts_every_commitment(self):
        for seed in range(12):
            ledger = build_ledger(seed)
            series = ledger.burndown_series("2026-03-01", 25)
            assert series[-1]["created"] == ledger.total_count(), seed
