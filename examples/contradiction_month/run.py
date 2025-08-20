"""Example: a month of contradictions — supersede, as-of, audit, deletion.

Fully offline on seeded synthetic data. It plants due-date, owner, and
decision contradictions, then demonstrates the four guarantees that make
contradictions safe to hold in long-term memory:

1. temporal supersede — a changed fact closes the old interval and opens
   a new one; both stay queryable;
2. as-of correctness — "what was true on date D" returns the right value
   before and after the change;
3. evidence-trust resolution — a deliberately overlapping pair is
   resolved by source trust, and the audit report records why;
4. right-to-forget — deleting a commitment cascades to its evidence and
   a tombstone blocks re-derivation.

Run:
    python examples/contradiction_month/run.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mnemofold.conflict import ConflictDetector, ConflictResolver, EvidenceSource
from mnemofold.deletion import DeletionEngine, DeletionReason, GraphDeletionTarget
from mnemofold.factory import FactoryConfig, WorkHistoryFactory
from mnemofold.temporal import IntervalFact, TemporalStore

SEED = 17
DAYS = 120


def _parse(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=None)


def main() -> int:
    factory = WorkHistoryFactory(
        seed=SEED,
        days=DAYS,
        config=FactoryConfig(contradiction_kinds=("due_date", "owner", "decision")),
    )
    events, manifest = factory.generate()
    typed = [event.to_event() for event in events]

    commitment_ts: dict[str, datetime] = {}
    contradiction_ts: dict[str, datetime] = {}
    for event in typed:
        ref = event.content.get("commitment_ref")
        if isinstance(ref, str) and str(event.content.get("subject", "")).startswith("Commitment:"):
            commitment_ts[ref] = event.timestamp.replace(tzinfo=None)
        cref = event.content.get("contradiction_ref")
        if isinstance(cref, str):
            contradiction_ts[cref] = event.timestamp.replace(tzinfo=None)

    store: TemporalStore[str] = TemporalStore()
    due_contradictions = [
        p
        for p in factory.planted_items()
        if p.kind == "contradiction" and p.data.get("change") == "due_date"
    ]
    asof_checks = 0
    asof_correct = 0
    for item in due_contradictions:
        ref = item.data["target_commitment"]
        start = commitment_ts.get(ref)
        change = contradiction_ts.get(item.item_id)
        if start is None or change is None or change <= start:
            continue
        key = f"commitment:{ref}:due"
        old_value = item.data["old_value"][:10]
        new_value = item.data["new_value"][:10]
        store.add(IntervalFact(key, old_value, start.isoformat(), change.isoformat()))
        store.add(IntervalFact(key, new_value, change.isoformat()))
        before = change - timedelta(days=1)
        after = change + timedelta(days=1)
        asof_checks += 2
        fact_before = store.as_of(key, before.isoformat())
        fact_after = store.as_of(key, after.isoformat())
        if fact_before is not None and fact_before.value == old_value:
            asof_correct += 1
        if fact_after is not None and fact_after.value == new_value:
            asof_correct += 1

    # Deliberate overlap resolved by evidence trust, with an audit trail.
    resolver = ConflictResolver()
    detector = ConflictDetector(resolver)
    overlap_key = "project:alpha:owner"
    overlap_start = "2025-01-10T00:00:00"
    store.add(
        IntervalFact(
            overlap_key,
            "alice",
            overlap_start,
            metadata={"source": EvidenceSource.UNVERIFIED.value, "source_id": "rumor"},
        )
    )
    store.add(
        IntervalFact(
            overlap_key,
            "bob",
            overlap_start,
            metadata={"source": EvidenceSource.VERIFIED.value, "source_id": "hr-record"},
        )
    )
    found = detector.scan(store)
    audit = resolver.audit_report(found)
    overlap_winner = next(
        (c for c in found if c.fact_key == overlap_key),
        None,
    )
    resolved_value = None
    if overlap_winner is not None:
        resolved_value = (
            overlap_winner.value_a if overlap_winner.winner == "a" else overlap_winner.value_b
        )

    # Right-to-forget cascade: commitment -> two evidence notes, plus a
    # legally-held note that must survive the cascade.
    targets = {
        "c1": GraphDeletionTarget("c1", "commitment", outgoing_relations=["e1", "e2", "held"]),
        "e1": GraphDeletionTarget("e1", "note"),
        "e2": GraphDeletionTarget("e2", "note"),
        "held": GraphDeletionTarget("held", "note"),
    }
    engine = DeletionEngine(
        get_target=targets.get,
        delete_item=lambda key, kind, reason, now: targets.pop(key, None) is not None,
        is_protected=lambda key: key == "held",
    )
    report = engine.delete("c1", DeletionReason.FORGET, _parse("2025-06-01T00:00:00"))
    deleted_ids = {entry.key for entry in report.deleted}
    resurrection_blocked = engine.is_deleted("c1") and "held" in report.blocked

    print("=== contradiction_month: supersede, as-of, audit, deletion ===")
    print(f"seed={SEED} days={DAYS} checksum={manifest.checksum}")
    print(f"planted contradictions: {manifest.planted_contradictions}")
    print(f"as-of answers correct: {asof_correct}/{asof_checks}  (synthetic ground truth)")
    print(f"overlap conflicts found: {len(found)}  winner value: {resolved_value}")
    print(f"audit by reason: {audit['by_reason']}")
    print(f"cascade deleted: {sorted(deleted_ids)}  blocked(protected): {report.blocked}")
    print(f"resurrection blocked by tombstone: {engine.is_deleted('c1')}")

    ok = (
        asof_checks > 0
        and asof_correct == asof_checks
        and resolved_value == "bob"  # verified source beats unverified
        and {"c1", "e1", "e2"} <= deleted_ids
        and "held" not in deleted_ids
        and resurrection_blocked
    )
    print(f"RESULT: {'OK' if ok else 'CHECK FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
