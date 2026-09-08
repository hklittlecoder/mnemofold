"""Example: integrity audit — verify, tamper, forget, resurrect, export.

A scripted session on a throwaway workspace that exercises every guard
the framework promises, with measured outcomes:

1. healthy audit — journal chain, trace chain, resurrection probe and
   projection stability all pass on a fresh workspace;
2. tamper detection — a COPY of the trace is edited; the reader rejects
   it while the original workspace stays intact;
3. right to be forgotten — preview first, then forget; the memory is
   unreachable afterwards;
4. resurrection probe — the forgotten content is smuggled back into the
   store behind the guard's back; ``verify_integrity`` catches it, and
   removing the smuggled item restores a clean audit;
5. export — the bundle manifest agrees with the live journal.

Everything is deterministic and offline; no real personal data.

Run:
    python examples/integrity_audit/run.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mnemofold.events import Event, EventType
from mnemofold.memory import MemoryItem, MemoryTier
from mnemofold.replay import TraceReader
from mnemofold.workspace import Workspace

BASE = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def scripted_events() -> list[Event]:
    events = [
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=BASE + timedelta(hours=i),
            content={
                "thread_id": "t-release",
                "subject": f"release mail {i}",
                "body": "milestone update" if i % 2 == 0 else "any update on the release?",
            },
        )
        for i in range(6)
    ]
    events.append(
        Event(
            event_type=EventType.NOTE,
            timestamp=BASE + timedelta(hours=7),
            content={"title": "decision", "text": "ship the release checklist friday"},
        )
    )
    return events


def main() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="mnemofold-integrity-") as tmp:
        root = Path(tmp)
        ws = Workspace(root / "ws")
        events = scripted_events()
        now = events[-1].timestamp.isoformat()
        ws.ingest_events(events, now=now)
        note_id = ws.remember("carry the release checklist", title="checklist", now=now)
        print("=== mnemofold integrity audit example ===")
        print(f"events: {len(events)} + 1 note; journal frames: {len(ws.journal)}")

        # 1) healthy audit
        report = ws.verify_integrity()
        checks.append(("healthy_verify_ok", report["ok"]))
        print(
            f"verify: ok={report['ok']} frames={report['frames_checked']} "
            f"digest={report['projection_digest'][:12]}"
        )

        # 2) tamper a COPY of the trace; the original must stay clean
        copy_dir = root / "tampered"
        shutil.copytree(root / "ws", copy_dir)
        trace_copy = copy_dir / "trace.jsonl"
        lines = trace_copy.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["entry"]["payload"]["tampered"] = True
        lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
        trace_copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
        checks.append(("tamper_detected", TraceReader(trace_copy).verify() is False))
        checks.append(("original_trace_intact", TraceReader(ws.trace.path).verify()))
        print("tamper: edited copy rejected, original intact")

        # 3) preview, then forget
        preview = ws.forget_preview(note_id)
        ws.forget(note_id, now=now, reason="example walkthrough")
        checks.append(("preview_planned_the_note", preview["total"] >= 1))
        checks.append(("forgotten_not_recallable", ws.recall(note_id) is None))
        print(f"forget: preview planned {preview['total']}, recall after: None")

        # 4) smuggle the content back behind the guard's back
        ws.store.add(MemoryItem(item_id=note_id, tier=MemoryTier.EPISODIC, content="smuggled"))
        caught = ws.verify_integrity()
        checks.append(
            (
                "resurrection_detected",
                (not caught["ok"]) and note_id in caught["resurrected_keys"],
            )
        )
        ws.store.remove(note_id)  # repair
        checks.append(("repaired_verify_ok", ws.verify_integrity()["ok"]))
        print(f"resurrection probe: detected={not caught['ok']}, repaired ok")

        # 5) export consistency
        manifest = ws.export_bundle(root / "bundle")
        checks.append(("bundle_events_match", manifest["events"] == len(ws.journal)))
        summary = TraceReader(ws.trace.path).summary()
        print(
            f"export: events={manifest['events']} memories={manifest['memories']} "
            f"tombstones={manifest['tombstones']}"
        )
        print(f"trace: {summary['entries']} entries {summary['by_kind']}")
        ws.close()

    failed = [name for name, ok in checks if not ok]
    print()
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"RESULT: {'OK' if not failed else 'FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
