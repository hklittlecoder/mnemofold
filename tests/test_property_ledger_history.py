"""Randomized lifecycles: transition()-only ledgers always audit clean.

Any status reached through the public API must be reproducible from the
history — the audit is the guard that makes tampering (direct field
writes) detectable instead of silent.
"""

import random

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus

TERMINAL = [CommitmentStatus.DONE, CommitmentStatus.CANCELLED, CommitmentStatus.SUPERSEDED]


def build(seed: int) -> CommitmentLedger:
    rng = random.Random(seed)
    ledger = CommitmentLedger()
    for i in range(rng.randint(3, 10)):
        cid = f"c{i}"
        ledger.add(
            Commitment(
                commitment_id=cid,
                owed_by=f"p{rng.randint(1, 3)}",
                owed_to=f"p{rng.randint(1, 3)}",
                description=f"task {i}",
                due_date=f"2026-03-{rng.randint(10, 28):02d}T17:00:00+00:00",
                created_at=f"2026-03-0{rng.randint(1, 9)}T09:00:00+00:00",
            )
        )
        for _ in range(rng.randint(0, 3)):
            target = rng.choice(TERMINAL + [CommitmentStatus.IN_PROGRESS, CommitmentStatus.OPEN])
            if not ledger.transition(cid, target, "2026-03-15T12:00:00+00:00"):
                break
    return ledger


class TestHistoryProperties:
    def test_public_api_ledgers_always_audit_clean(self):
        for seed in range(15):
            assert build(seed).verify_history()["ok"] is True, seed

    def test_single_field_tamper_always_detected(self):
        for seed in range(15):
            ledger = build(seed)
            victims = ledger.all_commitments()
            if not victims:
                continue
            target = victims[seed % len(victims)]
            original = target.status
            forged = (
                CommitmentStatus.DONE
                if original != CommitmentStatus.DONE
                else CommitmentStatus.OPEN
            )
            target.status = forged
            report = ledger.verify_history()
            assert report["ok"] is False, seed
            assert any(m["commitment_id"] == target.commitment_id for m in report["mismatches"])

    def test_history_grows_monotonically(self):
        ledger = build(3)
        counts = [len(ledger.transition_history())]
        ledger.transition(
            ledger.all_commitments()[0].commitment_id,
            CommitmentStatus.IN_PROGRESS,
            "2026-03-16T09:00:00+00:00",
        )
        counts.append(len(ledger.transition_history()))
        assert counts[1] >= counts[0]
