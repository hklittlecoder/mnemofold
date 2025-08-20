"""Example: nightly folding — consolidation, recurrence mining, playbooks.

Fully offline on a seeded synthetic history with repeated workflows
planted. Demonstrates the three jobs of the nightly fold:

1. promotion — a high-salience episodic memory becomes a semantic fact;
2. near-duplicate merging — two almost-identical semantic notes merge,
   the loser recorded in the winner's provenance;
3. recurrence mining — a repeated step sequence is proposed as a
   playbook, which we then turn into an approved, active playbook.

A second fold proves idempotence: nothing new merges or promotes. All
numbers are measured from this synthetic run.

Run:
    python examples/folding_demo/run.py
"""

from __future__ import annotations

from mnemofold.factory import FactoryConfig, WorkHistoryFactory
from mnemofold.fold import Folder
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.playbooks import (
    Playbook,
    PlaybookLibrary,
    PlaybookStatus,
    PlaybookStep,
)

SEED = 23
DAYS = 120
REPEATS = 5
TS = "2025-06-01T02:00:00+00:00"


def build_store(factory: WorkHistoryFactory) -> MemoryStore:
    events, _ = factory.generate()
    store = MemoryStore()
    for synthetic in events:
        event = synthetic.to_event()
        payload = event.content
        if payload.get("workflow") != "release":
            continue
        store.add(
            MemoryItem(
                item_id=str(payload["task_id"]),
                tier=MemoryTier.EPISODIC,
                content=f"{payload['step']} for {payload.get('project', 'general')}",
                title=str(payload["step"]),
                created_at=event.timestamp.isoformat(),
                metadata={
                    "workflow": payload["workflow"],
                    "run_id": payload["run_id"],
                    "step": payload["step"],
                },
            )
        )
    # a high-salience episodic note that folding will promote to semantic
    store.add(
        MemoryItem(
            item_id="hot-episode",
            tier=MemoryTier.EPISODIC,
            content="important planning decision for the roadmap",
            title="Planning",
            salience=0.9,
        )
    )
    # a near-duplicate pair of semantic notes that folding will merge
    store.add(
        MemoryItem(
            item_id="dup-a",
            tier=MemoryTier.SEMANTIC,
            content="quarterly budget review with finance team",
            salience=0.5,
        )
    )
    store.add(
        MemoryItem(
            item_id="dup-b",
            tier=MemoryTier.SEMANTIC,
            content="quarterly budget review with finance team!",
            salience=0.3,
        )
    )
    return store


def main() -> int:
    factory = WorkHistoryFactory(
        seed=SEED, days=DAYS, config=FactoryConfig(workflow_repeats=REPEATS)
    )
    store = build_store(factory)
    folder = Folder(min_episodes_for_recurrence=3)

    report = folder.fold(store, TS, fold_id="nightly-demo")
    second = folder.fold(store, TS, fold_id="nightly-demo-2")

    workflow_props = [
        p for p in report.recurrence_proposals if p.get("kind") == "workflow_sequence"
    ]

    library = PlaybookLibrary()
    approved_ids: list[str] = []
    for prop in workflow_props:
        pb_id = f"pb-{prop['workflow']}"
        steps = [PlaybookStep(step_id=f"s{j}", title=step) for j, step in enumerate(prop["steps"])]
        library.add(
            Playbook(
                playbook_id=pb_id,
                name=f"{prop['workflow']} playbook",
                status=PlaybookStatus.PROPOSED,
                steps=steps,
                confidence=prop["confidence"],
                tags={prop["workflow"]},
                derived_from=list(prop["run_ids"]),
            )
        )
        library.approve(pb_id, approver="alice", timestamp=TS)
        library.activate(pb_id)
        approved_ids.append(pb_id)

    print("=== folding_demo: nightly consolidation on synthetic history ===")
    print(f"seed={SEED} days={DAYS} workflow_repeats={REPEATS}")
    print(f"items before/after first fold: {report.items_before} -> {report.items_after}")
    print(
        f"merges: {len(report.merges)}  rejected: {len(report.rejected)}  "
        f"new semantic: {len(report.new_semantic)}"
    )
    print(
        f"recurrence proposals: {len(report.recurrence_proposals)} "
        f"(workflow sequences: {len(workflow_props)})"
    )
    for prop in workflow_props[:3]:
        steps = " -> ".join(prop["steps"])
        print(f"  workflow '{prop['workflow']}': {steps} x{prop['run_count']}")
    print(
        f"second fold idempotent: merges={len(second.merges)} "
        f"new_semantic={len(second.new_semantic)}"
    )
    print(f"approved playbooks: {approved_ids}")
    print()
    print("--- fold report (markdown, first 360 chars) ---")
    print(report.to_markdown()[:360])

    top = library.get(approved_ids[0]) if approved_ids else None
    ok = (
        len(report.merges) >= 1
        and len(report.new_semantic) >= 1
        and len(workflow_props) >= 1
        and any(p["run_count"] >= REPEATS for p in workflow_props)
        and second.merges == []
        and second.new_semantic == []
        and top is not None
        and top.status == PlaybookStatus.ACTIVE
    )
    print(f"RESULT: {'OK' if ok else 'CHECK FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
