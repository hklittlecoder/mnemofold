"""Example: playbook lifecycle — mine, propose, approve, run, revise.

On a seeded 120-day synthetic history with a repeated ``release``
workflow planted, this walkthrough covers the full procedural-memory
loop:

1. mining — the nightly fold proposes a playbook from the repeated
   step sequence (measured run_count and confidence);
2. suggestion — the library surfaces the proposal for matching tags;
3. approval gating — a ``PlaybookRunner`` submits an approval request;
   the run executes ONLY after the queue records an approval, and a
   denied request never touches a tool;
4. execution — every step runs through the real tool registry and the
   run is counted exactly once;
5. revision — an edited step list becomes a v2 draft with provenance,
   and the version diff names the removed step.

All numbers are measured from this run. Offline and deterministic.

Run:
    python examples/playbook_lifecycle/run.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from mnemofold.approvals import ApprovalQueue
from mnemofold.factory import FactoryConfig, WorkHistoryFactory
from mnemofold.fold import Folder
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.playbooks import (
    Playbook,
    PlaybookLibrary,
    PlaybookRunner,
    PlaybookStatus,
    PlaybookStep,
)
from mnemofold.tools import build_default_registry

SEED = 23
DAYS = 120
REPEATS = 5
TS = "2025-06-01T02:00:00+00:00"
NOW = datetime(2025, 6, 1, 9, 0, tzinfo=UTC)


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
    return store


def main() -> int:
    checks: list[tuple[str, bool]] = []
    factory = WorkHistoryFactory(
        seed=SEED, days=DAYS, config=FactoryConfig(workflow_repeats=REPEATS)
    )
    store = build_store(factory)
    print(f"=== mnemofold playbook lifecycle example (seed={SEED}) ===")
    print(f"workflow memories: {store.total_count()}")

    # 1) mining
    report = Folder(min_episodes_for_recurrence=3).fold(store, TS, fold_id="pb-demo")
    proposals = [p for p in report.recurrence_proposals if p.get("kind") == "workflow_sequence"]
    print(f"mined proposals: {len(proposals)}")
    checks.append(("recurrence_mined", len(proposals) >= 1))
    if not proposals:
        print("RESULT: FAILED")
        return 1
    prop = proposals[0]
    print(
        f"  - workflow {prop['workflow']!r}: steps={prop['steps']} "
        f"runs={prop['run_count']} confidence={prop['confidence']}"
    )

    # 2) proposal -> playbook -> suggestion
    steps = [
        PlaybookStep(step_id=f"s{i}", title=str(step), tool="echo", inputs={"message": str(step)})
        for i, step in enumerate(prop["steps"])
    ]
    pb = Playbook(
        playbook_id="pb-release",
        name=f"{prop['workflow']} playbook",
        description="learned from recurrence mining",
        status=PlaybookStatus.PROPOSED,
        steps=steps,
        tags={prop["workflow"]},
        confidence=prop["confidence"],
        derived_from=list(prop["run_ids"]),
    )
    library = PlaybookLibrary()
    library.add(pb)
    suggested = library.suggest({prop["workflow"]})
    checks.append(("suggestion_found", any(s.playbook_id == "pb-release" for s in suggested)))

    # 3) + 4) approval-gated execution
    queue = ApprovalQueue()
    runner = PlaybookRunner(library=library, queue=queue, registry=build_default_registry())
    library.approve("pb-release", approver="ana", timestamp=TS)
    library.activate("pb-release")

    approved_id = runner.request_run("pb-release", requester="ana", approver="boss", now=NOW)
    denied_id = runner.request_run("pb-release", requester="ana", approver="boss", now=NOW)
    assert approved_id is not None and denied_id is not None
    queue.decide(denied_id, False, NOW, note="not this week")
    denied_report = runner.execute(denied_id)
    checks.append(("denied_run_blocked", denied_report.status == "not_approved"))
    checks.append(("denied_run_not_counted", pb.run_count == 0))

    queue.decide(approved_id, True, NOW)
    run_report = runner.execute(approved_id)
    print(
        f"run: status={run_report.status} steps={len(run_report.step_results)} "
        f"run_count={pb.run_count}"
    )
    checks.append(("approved_run_completed", run_report.status == "completed"))
    checks.append(("all_steps_executed", all(r.success for r in run_report.step_results)))
    checks.append(("run_count_incremented", pb.run_count == 1))

    # 5) revision + diff
    revised = library.create_revision("pb-release", steps[:-1])
    checks.append(
        (
            "revision_created",
            revised is not None and revised.version == 2 and revised.status == PlaybookStatus.DRAFT,
        )
    )
    assert revised is not None
    diff = library.diff_versions("pb-release", revised.playbook_id)
    print(f"revision v2: removed={diff['steps_removed']} meta={diff['meta_changes']}")
    checks.append(("diff_shows_removed_step", diff["steps_removed"] == [steps[-1].step_id]))

    failed = [name for name, ok in checks if not ok]
    print()
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"RESULT: {'OK' if not failed else 'FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
