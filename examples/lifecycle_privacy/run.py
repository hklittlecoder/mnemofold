"""Example: memory lifecycle & privacy — seal, fold, forget, verify.

One seeded synthetic history, one throwaway workspace, and a full pass
through the mechanisms that keep personal data under control:

1. privacy — a note containing PII is detected, sealed into reversible
   tokens by a salted ``RedactionVault``, and only the SEALED text is
   remembered;
2. consolidation — the nightly fold runs over the projected memories;
3. retrieval — an ask() query returns citations that all resolve;
4. right to be forgotten — ``forget_preview`` shows the impact first,
   then ``forget`` cascades, tombstones, and blocks recall;
5. audit — ``verify_integrity`` and the trace summary confirm the
   journal, trace and tombstone layers agree.

Every printed number is measured from this run. Offline, deterministic,
no real personal data: the PII below is synthetic.

Run:
    python examples/lifecycle_privacy/run.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from mnemofold.factory import WorkHistoryFactory
from mnemofold.privacy import RedactionVault, detect_pii
from mnemofold.replay import TraceReader
from mnemofold.workspace import Workspace

SEED = 31
DAYS = 10
RAW_NOTE = "Mail ana.chen@corp.example or +1-555-0142 about card 4111 1111 1111 1111."


def main() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="mnemofold-lifecycle-") as tmp:
        factory = WorkHistoryFactory(seed=SEED, days=DAYS)
        synthetic, manifest = factory.generate()
        events = [e.to_event() for e in synthetic]
        now = events[-1].timestamp

        print(f"=== mnemofold lifecycle & privacy example (seed={SEED}) ===")
        print(f"history: {len(events)} events, checksum {manifest.checksum}")

        with Workspace(Path(tmp) / "ws") as ws:
            ingested = ws.ingest_events(events, now=now)
            print(f"ingested: {ingested} events -> {ws.store.total_count()} memories")

            # 1) privacy: detect, seal, remember only the sealed text
            found = detect_pii(RAW_NOTE)
            vault = RedactionVault(salt="example-salt")
            sealed = vault.seal(RAW_NOTE)
            note_id = ws.remember(
                sealed, title="contact follow-up (sealed)", tags=["privacy"], now=now
            )
            print(f"privacy: detected {len(found)} PII spans; sealed note {note_id}")
            checks.append(("pii_detected", len(found) >= 3))
            checks.append(("sealed_hides_email", "ana.chen@corp.example" not in sealed))
            checks.append(("sealed_hides_card", "4111" not in sealed))
            checks.append(("vault_unseal_restores", vault.unseal(sealed) == RAW_NOTE))

            # 2) consolidation
            report = ws.fold(now)
            print(
                f"fold: {report.items_before} -> {report.items_after} memories "
                f"({len(report.merges)} merges)"
            )

            # 3) retrieval with resolvable citations
            hits = ws.ask("milestone", top_k=5, now=now)
            citations_ok = all(ws.recall(h.item_id) is not None for h in hits)
            print(f"recall: {len(hits)} hits for 'milestone'; citations resolve: {citations_ok}")
            checks.append(("citations_resolve", citations_ok))

            # 4) right to be forgotten, preview first
            preview = ws.forget_preview(note_id)
            checks.append(
                (
                    "preview_plans_the_note",
                    any(e["key"] == note_id for e in preview["would_delete"]),
                )
            )
            ws.forget(note_id, now=now, reason="example walkthrough")
            gone = ws.recall(note_id) is None
            print(f"forget: preview planned {preview['total']}, recall after forget: {gone}")
            checks.append(("forgotten_not_recallable", gone))

            # 5) audit layers
            integrity = ws.verify_integrity()
            summary = TraceReader(ws.trace.path).summary()
            print(
                f"audit: integrity ok={integrity['ok']}, "
                f"tombstones={integrity['tombstones']}, "
                f"trace entries={summary['entries']}"
            )
            checks.append(("integrity_ok", integrity["ok"]))
            checks.append(("trace_has_receipts", summary["by_kind"].get("receipt", 0) >= 3))

    failed = [name for name, ok in checks if not ok]
    print()
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"RESULT: {'OK' if not failed else 'FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
