"""Command-line interface for mnemofold.

Subcommands are grouped by functionality: ingestion, query, reports,
memory ops, evaluation, and utilities.  Each subcommand has its own
help text and exit codes.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from . import __version__

if TYPE_CHECKING:
    from .fold import FoldReport
    from .workspace import Workspace


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="mnemofold",
        description="mnemofold — offline long-term memory framework for personal agents",
    )
    parser.add_argument("--version", action="version", version=f"mnemofold {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # version
    p_version = sub.add_parser("version", help="print version and exit")
    p_version.set_defaults(func=_cmd_version)

    # eval
    p_eval = sub.add_parser("eval", help="run evaluation on synthetic history")
    p_eval.add_argument("--seed", type=int, default=42, help="random seed")
    p_eval.add_argument("--days", type=int, default=30, help="days of history")
    p_eval.add_argument("--json", action="store_true", help="output JSON scorecard")
    p_eval.add_argument(
        "--slices",
        choices=["none", "projects", "roles"],
        default="none",
        help="also run per-slice commitment scorecards",
    )
    p_eval.add_argument(
        "--svg", metavar="OUT", help="write an aggregate scorecard SVG chart to OUT"
    )
    p_eval.set_defaults(func=_cmd_eval)

    # demo
    p_demo = sub.add_parser("demo", help="run a full seeded persona week offline")
    p_demo.add_argument("--seed", type=int, default=42, help="random seed")
    p_demo.add_argument("--days", type=int, default=7, help="days of demo history")
    p_demo.set_defaults(func=_cmd_demo)

    # replay
    p_replay = sub.add_parser("replay", help="replay a recorded trace")
    p_replay.add_argument("trace", help="path to JSONL trace file")
    p_replay.set_defaults(func=_cmd_replay)

    # diff
    p_diff = sub.add_parser("diff", help="diff two trace files")
    p_diff.add_argument("trace_a", help="first trace file")
    p_diff.add_argument("trace_b", help="second trace file")
    p_diff.set_defaults(func=_cmd_diff)

    # ledger
    p_ledger = sub.add_parser("ledger", help="list commitments and status")
    p_ledger.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_ledger.add_argument("--days", type=int, default=30, help="days of history")
    p_ledger.add_argument("--status", help="filter by status (open/done/overdue)")
    p_ledger.add_argument("--json", action="store_true", help="output JSON")
    p_ledger.add_argument("--aging", action="store_true", help="report due-time aging buckets")
    p_ledger.set_defaults(func=_cmd_ledger)

    # triage
    p_triage = sub.add_parser("triage", help="score and rank inbox items")
    p_triage.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_triage.add_argument("--days", type=int, default=14, help="days of history")
    p_triage.add_argument("--top", type=int, default=10, help="show top N items")
    p_triage.add_argument("--json", action="store_true", help="output JSON results")
    p_triage.set_defaults(func=_cmd_triage)

    # fold
    p_fold = sub.add_parser("fold", help="run nightly consolidation fold")
    p_fold.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_fold.add_argument("--days", type=int, default=30, help="days of history to fold")
    p_fold.add_argument("--json", action="store_true", help="output JSON fold report")
    p_fold.add_argument("--db", help="fold this workspace instead of demo data")
    p_fold.add_argument(
        "--now", default="", help="ISO fold timestamp with --db (default: last event)"
    )
    p_fold.add_argument("--html", metavar="OUT", help="write the HTML fold report to OUT")
    p_fold.set_defaults(func=_cmd_fold)

    # asof
    p_asof = sub.add_parser("asof", help="query state as of a specific date")
    p_asof.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_asof.add_argument("--days", type=int, default=30, help="total days of history")
    p_asof.add_argument("--date", help="query date (YYYY-MM-DD), default: halfway")
    p_asof.set_defaults(func=_cmd_asof)

    # context
    p_context = sub.add_parser("context", help="build a budgeted context pack")
    p_context.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_context.add_argument("--days", type=int, default=30, help="days of history")
    p_context.add_argument("--budget", type=int, default=2000, help="token budget")
    p_context.add_argument("--profile", default="meeting_prep", help="packing profile")
    p_context.add_argument("--json", action="store_true", help="output the pack as JSON")
    p_context.set_defaults(func=_cmd_context)

    # prep
    p_prep = sub.add_parser("prep", help="generate meeting prep packet")
    p_prep.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_prep.add_argument("--days", type=int, default=14, help="days of history to include")
    p_prep.add_argument("--meeting", default="sync", help="meeting identifier")
    p_prep.add_argument("--json", action="store_true", help="output JSON")
    p_prep.set_defaults(func=_cmd_prep)

    # privacy
    p_privacy = sub.add_parser("privacy", help="scan text for PII and redact")
    p_privacy.add_argument("text", nargs="?", help="text to scan (or use --demo)")
    p_privacy.add_argument("--demo", action="store_true", help="run on demo text")
    p_privacy.add_argument(
        "--mode",
        default="mask",
        choices=["mask", "hash", "remove", "seal"],
        help="redaction mode (seal requires --vault)",
    )
    p_privacy.add_argument("--salt", default="", help="salt for hash mode / new vaults")
    p_privacy.add_argument(
        "--vault", help="redaction vault file (required for seal mode and --unseal)"
    )
    p_privacy.add_argument(
        "--unseal", action="store_true", help="restore sealed text using --vault"
    )
    p_privacy.set_defaults(func=_cmd_privacy)

    # triggers
    p_triggers = sub.add_parser("triggers", help="list active proactive triggers")
    p_triggers.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_triggers.add_argument("--days", type=int, default=30, help="days of history")
    p_triggers.add_argument("--json", action="store_true", help="output JSON")
    p_triggers.add_argument(
        "--db", help="derive from this workspace (commitments + journal threads)"
    )
    p_triggers.add_argument(
        "--now", default="", help="ISO instant for the tick (default: last journal event)"
    )
    p_triggers.set_defaults(func=_cmd_triggers)

    # ingest
    p_ingest = sub.add_parser("ingest", help="ingest events into a workspace")
    p_ingest.add_argument("--db", required=True, help="workspace directory")
    p_ingest.add_argument("--seed", type=int, default=42, help="synthetic history seed")
    p_ingest.add_argument("--days", type=int, default=30, help="days of synthetic history")
    p_ingest.add_argument("--jsonl", help="ingest from a JSONL event file instead")
    p_ingest.set_defaults(func=_cmd_ingest)

    # export
    p_export = sub.add_parser("export", help="export ledger and workspace stats")
    p_export.add_argument("--db", required=True, help="workspace directory")
    p_export.add_argument("--format", default="json", choices=["json", "markdown"])
    p_export.add_argument("--out", help="write to file instead of stdout")
    p_export.add_argument(
        "--bundle",
        metavar="DIR",
        help="write a self-describing workspace bundle (ledger, snapshot, manifest) into DIR",
    )
    p_export.set_defaults(func=_cmd_export)

    # remember
    p_remember = sub.add_parser("remember", help="record a note into the workspace")
    p_remember.add_argument("--db", required=True, help="workspace directory")
    p_remember.add_argument("--text", required=True, help="note text")
    p_remember.add_argument("--title", default="", help="optional title")
    p_remember.add_argument("--tags", default="", help="comma-separated tags")
    p_remember.add_argument("--now", required=True, help="ISO instant for the note")
    p_remember.set_defaults(func=_cmd_remember)

    # forget
    p_forget = sub.add_parser("forget", help="forget a memory (right to be forgotten)")
    p_forget.add_argument("--db", required=True, help="workspace directory")
    p_forget.add_argument("item_id", help="memory id to forget")
    p_forget.add_argument("--reason", default="", help="reason recorded on the tombstone")
    p_forget.add_argument("--now", required=True, help="ISO instant of the request")
    p_forget.add_argument(
        "--preview", action="store_true", help="show the impact report without deleting"
    )
    p_forget.add_argument(
        "--report",
        default="text",
        choices=["text", "json", "markdown"],
        help="deletion report format",
    )
    p_forget.set_defaults(func=_cmd_forget)

    # recall
    p_recall = sub.add_parser("recall", help="fetch one memory by id")
    p_recall.add_argument("--db", required=True, help="workspace directory")
    p_recall.add_argument("item_id", help="memory id to recall")
    p_recall.set_defaults(func=_cmd_recall)

    # ask
    p_ask = sub.add_parser("ask", help="search the workspace with filters")
    p_ask.add_argument("--db", required=True, help="workspace directory")
    p_ask.add_argument("query", help="query text with optional tag:/person:/before: filters")
    p_ask.add_argument("--top", type=int, default=5, help="max results")
    p_ask.add_argument("--as-of", default="", help="only results created at or before this instant")
    p_ask.add_argument("--json", action="store_true", help="output JSON results")
    p_ask.add_argument("--explain", action="store_true", help="include per-term BM25 contributions")
    p_ask.set_defaults(func=_cmd_ask)

    # standup
    p_standup = sub.add_parser("standup", help="standup report from workspace ledger")
    p_standup.add_argument("--db", required=True, help="workspace directory")
    p_standup.add_argument("--today", help="ISO instant for 'today' (default: last event)")
    p_standup.add_argument("--html", action="store_true", help="output HTML")
    p_standup.add_argument("--json", action="store_true", help="output JSON (takes precedence)")
    p_standup.set_defaults(func=_cmd_standup)

    # review
    p_review = sub.add_parser("review", help="weekly review from workspace ledger")
    p_review.add_argument("--db", required=True, help="workspace directory")
    p_review.add_argument("--start", required=True, help="ISO week start")
    p_review.add_argument("--end", required=True, help="ISO week end")
    p_review.add_argument("--html", action="store_true", help="output HTML")
    p_review.add_argument("--json", action="store_true", help="output JSON (takes precedence)")
    p_review.set_defaults(func=_cmd_review)

    # playbooks
    p_playbooks = sub.add_parser("playbooks", help="mine playbook proposals from workspace memory")
    p_playbooks.add_argument("--db", required=True, help="workspace directory")
    p_playbooks.add_argument("--min-repeats", type=int, default=3, help="recurrence floor")
    p_playbooks.add_argument("--json", action="store_true", help="output JSON proposals")
    p_playbooks.set_defaults(func=_cmd_playbooks)

    # verify
    p_verify = sub.add_parser("verify", help="verify workspace integrity (chains, tombstones)")
    p_verify.add_argument("--db", required=True, help="workspace directory")
    p_verify.add_argument("--json", action="store_true", help="output the JSON report")
    p_verify.set_defaults(func=_cmd_verify)

    # decay
    p_decay = sub.add_parser("decay", help="apply retention decay to a workspace")
    p_decay.add_argument("--db", required=True, help="workspace directory")
    p_decay.add_argument("--now", required=True, help="ISO instant for the decay pass")
    p_decay.add_argument("--json", action="store_true", help="output counters as JSON")
    p_decay.set_defaults(func=_cmd_decay)

    return parser


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from .evaluation import (
        ScenarioConfig,
        run_commitment_slices,
        run_role_slices,
        run_suite,
    )
    from .factory import WorkHistoryFactory

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, manifest = factory.generate()
    suite = run_suite(ScenarioConfig(seed=args.seed, days=args.days))
    slices = []
    if args.slices == "projects":
        slices = run_commitment_slices(ScenarioConfig(seed=args.seed, days=args.days))
    elif args.slices == "roles":
        slices = run_role_slices(ScenarioConfig(seed=args.seed, days=args.days))
    if args.svg:
        from pathlib import Path

        from .evaluation import scorecard_svg_rows
        from .reports import render_scorecard_svg

        svg = render_scorecard_svg(scorecard_svg_rows(suite.aggregate))
        Path(args.svg).write_text(svg, encoding="utf-8")
        # stderr keeps stdout machine-readable (JSON mode)
        print(f"Wrote scorecard SVG to {args.svg}", file=sys.stderr)

    if args.json:
        import json

        payload = {
            "scenario": f"eval-seed{args.seed}-{args.days}d",
            "checksum": manifest.checksum,
            "metrics": [
                {"name": "event_count", "value": float(len(events))},
                {
                    "name": "planted_commitments",
                    "value": float(manifest.planted_commitments),
                },
                {"name": "planted_decisions", "value": float(manifest.planted_decisions)},
                {
                    "name": "planted_contradictions",
                    "value": float(manifest.planted_contradictions),
                },
            ],
            "cards": [card.to_dict() for card in suite.cards],
            "aggregate": suite.aggregate.to_dict(),
            "overall_pass": suite.overall_pass(),
            "slices": [result.scorecard.to_dict() for result in slices],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"=== mnemofold eval (seed={args.seed}, days={args.days}) ===")
        print(f"Events: {len(events)}")
        print(f"Planted commitments: {manifest.planted_commitments}")
        print(f"Planted decisions: {manifest.planted_decisions}")
        print(f"Planted contradictions: {manifest.planted_contradictions}")
        print(f"Checksum: {manifest.checksum}")
        for card in suite.cards:
            verdict = "PASS" if card.overall_pass() else "FAIL"
            print(f"[{verdict}] {card.scenario} ({card.pass_count()}/{len(card.metrics)})")
            for metric in card.metrics:
                print(f"    {metric.name}: {metric.value:.4f} [{metric.status.value}]")
        print(f"Aggregate pass: {suite.aggregate.overall_pass()}")
        for result in slices:
            verdict = "PASS" if result.scorecard.overall_pass() else "FAIL"
            print(f"[{verdict}] slice {result.scorecard.scenario}")

    return 0 if suite.overall_pass() else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    import tempfile

    from .context import PackingProfile
    from .evaluation import MetricResult, ScenarioConfig, Scorecard, run_commitment_scenario
    from .factory import WorkHistoryFactory
    from .triage import TriageItem
    from .workspace import Workspace

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, manifest = factory.generate()

    print(f"=== mnemofold demo (seed={args.seed}, days={args.days}) ===")
    print(f"Generated {len(events)} events across {args.days} days")
    print(f"  - planted commitments: {manifest.planted_commitments}")
    print(f"  - planted decisions: {manifest.planted_decisions}")
    print(f"  - planted contradictions: {manifest.planted_contradictions}")
    print(f"Checksum: {manifest.checksum}")
    print()

    # Event type breakdown
    type_counts: dict[str, int] = {}
    for ev in events:
        type_counts[ev.event_type] = type_counts.get(ev.event_type, 0) + 1
    print("Event type breakdown:")
    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {etype}: {count}")
    print()

    now = events[-1].timestamp if events else "2026-01-01T00:00:00+00:00"
    today = now[:10]
    typed = [ev.to_event() for ev in events]
    budget = 400

    # Full offline pipeline on a throwaway workspace:
    # ingest -> fold -> recall -> context pack -> prep -> triage -> standup
    with tempfile.TemporaryDirectory(prefix="mnemofold-demo-") as workdir, Workspace(workdir) as ws:
        ingested = ws.ingest_events(typed, now=now)
        print(f"Ingested {ingested} events into the workspace")
        print(f"  - commitments extracted: {ws.ledger.total_count()}")
        print(f"  - memories projected: {ws.store.total_count()}")
        print()

        report = ws.fold(now)
        print(
            f"Fold: {report.items_before} -> {report.items_after} memories "
            f"({len(report.merges)} merges, "
            f"{len(report.recurrence_proposals)} playbook proposals)"
        )
        print()

        hits = ws.ask("milestone", top_k=3, now=now)
        print(f"Recall: query 'milestone' -> {len(hits)} cited memories")
        if hits:
            item = ws.recall(hits[0].item_id, now=now)
            title = item.title if item is not None else "(gone)"
            print(f"  - top: {title[:60]}")
        print()

        pack = ws.context_pack(
            "milestone",
            budget_tokens=budget,
            profile=PackingProfile.MEETING_PREP,
            now=now,
        )
        print(f"Context pack: {pack.total_tokens}/{pack.budget} tokens, {len(pack.items)} items")
        print()

        packet = ws.prep("demo-sync", "Demo sync", ["p1"], now=now)
        print(f"Meeting prep: {packet.total_items} cited items for 'Demo sync'")
        print()

        mail_events = [e for e in events if e.event_type in ("mail_received", "mail_sent")][:10]
        items = [
            TriageItem(
                item_id=ev.event_id,
                title=ev.payload.get("subject", "(no subject)"),
                sender=ev.payload.get("from", "unknown"),
                received_at=ev.timestamp,
                content=ev.payload.get("body", ""),
                has_explicit_ask="?" in ev.payload.get("body", ""),
                thread_length=1,
                sender_importance=0.6,
            )
            for ev in mail_events
        ]
        titles = {item.item_id: item.title for item in items}
        results, plan = ws.triage(items, now)
        results.sort(key=lambda r: (-r.score, r.item_id))
        print("Top triaged mail items:")
        for result in results[:5]:
            reason_str = ", ".join(result.reasons[:3])
            title = titles.get(result.item_id, "")
            print(f"  [{result.score:.3f}] {title[:50]} ({reason_str})")
        print(
            f"  batch plan: act_now={len(plan.act_now)} "
            f"review={len(plan.review)} defer={len(plan.defer)}"
        )
        print()

        data = ws.standup(today, now=now)
        print(f"Standup for {data.date}:")
        print(f"  Completed: {len(data.completed)}")
        print(f"  In progress: {len(data.in_progress)}")
        print(f"  Planned: {len(data.planned)}")
        print(f"  Blockers: {len(data.blockers)}")
        print(f"  Open commitments: {len(data.open_commitments)}")
        print(f"  Overdue: {len(data.overdue)}")
        print(f"  Pending decisions: {len(data.pending_decisions)}")
        print()

    # Measured scores on the synthetic history (planted ground truth)
    scenario = run_commitment_scenario(ScenarioConfig(seed=args.seed, days=args.days))
    measured = scenario.measurements
    print("Measured on synthetic history (planted ground truth):")
    print(
        f"  - commitment recall: {measured['commitment_recall']:.3f} "
        f"({measured['recovered']}/{measured['planted']})"
    )
    print(f"  - overdue F1: {measured['overdue']['f1']:.3f}")
    print()

    # Scorecard
    sc = Scorecard(scenario=f"demo-seed{args.seed}")
    sc.add(MetricResult(name="events_generated", value=float(len(events))))
    sc.add(MetricResult(name="mail_triage_scored", value=float(len(results))))
    sc.add(
        MetricResult(
            name="deterministic_checksum",
            value=1.0 if manifest.checksum else 0.0,
            threshold=1.0,
            higher_is_better=True,
        )
    )
    sc.add(
        MetricResult(
            name="commitment_recall",
            value=measured["commitment_recall"],
        )
    )
    sc.add(
        MetricResult(
            name="context_budget_respected",
            value=1.0 if pack.total_tokens <= pack.budget else 0.0,
            threshold=1.0,
            higher_is_better=True,
        )
    )
    print(f"Scorecard pass: {sc.overall_pass()} ({sc.pass_count()}/{len(sc.metrics)} metrics)")
    print("=== Demo complete ===")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    from .replay import TraceReader

    try:
        reader = TraceReader(args.trace)
        if not reader.verify():
            print(f"ERROR: trace verification failed: {args.trace}", file=sys.stderr)
            return 2
        entries = reader.entries()
        print(f"Trace: {args.trace}")
        print(f"Entries: {len(entries)}")
        kinds: dict[str, int] = {}
        for e in entries:
            k = e.kind.value
            kinds[k] = kinds.get(k, 0) + 1
        for kind, count in sorted(kinds.items()):
            print(f"  {kind}: {count}")
        return 0
    except FileNotFoundError:
        print(f"ERROR: trace not found: {args.trace}", file=sys.stderr)
        return 1


def _cmd_diff(args: argparse.Namespace) -> int:
    from .replay import trace_diff

    result = trace_diff(args.trace_a, args.trace_b)
    print(f"A: {args.trace_a} ({result['a_count']} entries)")
    print(f"B: {args.trace_b} ({result['b_count']} entries)")
    print(f"Matching: {result['matching']}")
    print(f"Equal: {result['equal']}")
    if result["first_mismatch"] is not None:
        print(f"First mismatch at index: {result['first_mismatch']}")
    return 0 if result["equal"] else 1


def _cmd_ledger(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .ledger import Commitment, CommitmentLedger, CommitmentStatus

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    ledger = CommitmentLedger()
    for item in factory.planted_items():
        if item.kind == "commitment":
            c = Commitment(
                commitment_id=item.item_id,
                description=item.data["description"],
                owed_by=item.data["owed_by"],
                owed_to=item.data["owed_to"],
                due_date=item.data["due_date"],
            )
            ledger.add(c)

    if args.status:
        status_map = {
            "open": CommitmentStatus.OPEN,
            "done": CommitmentStatus.DONE,
            "cancelled": CommitmentStatus.CANCELLED,
            "in_progress": CommitmentStatus.IN_PROGRESS,
        }
        target = status_map.get(args.status)
        if target is not None:
            ledger.by_status(target)
        else:
            ledger.by_status(CommitmentStatus.OPEN)
    else:
        ledger.by_status(CommitmentStatus.OPEN)

    if args.aging:
        import json as json_mod

        now = events[-1].timestamp if events else "2026-01-01T00:00:00+00:00"
        report = ledger.aging_report(now)
        if args.json:
            print(json_mod.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"=== Ledger aging as of {now} ===")
            for bucket in ("overdue", "due_today", "due_this_week", "later", "no_due"):
                ids = report[bucket]
                suffix = f" ({', '.join(ids)})" if ids else ""
                print(f"  {bucket}: {len(ids)}{suffix}")
            print(f"  total active: {report['total_active']}")
        return 0

    if args.json:
        print(ledger.to_json())
    else:
        print(ledger.to_markdown())
        print()
        print(f"Total: {ledger.total_count()}")

    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .triage import TriageItem, TriageScorer

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    scorer = TriageScorer()
    now = events[-1].timestamp if events else "2026-01-01T00:00:00+00:00"
    results = []
    for ev in events:
        if ev.event_type not in ("mail_received", "mail_sent"):
            continue
        item = TriageItem(
            item_id=ev.event_id,
            title=ev.payload.get("subject", "(no subject)"),
            sender=ev.payload.get("from", "unknown"),
            received_at=ev.timestamp,
            content=ev.payload.get("body", ""),
            has_explicit_ask="?" in ev.payload.get("body", ""),
            thread_length=1,
            sender_importance=0.6,
        )
        result = scorer.score(item, now=now)
        results.append((result.score, item, result.reasons, result))

    results.sort(key=lambda x: -x[0])
    top_n = results[: args.top]

    if args.json:
        import json

        payload = {
            "scored": len(results),
            "shown": len(top_n),
            "top": [
                {**result.to_dict(), "title": item.title, "sender": item.sender}
                for _score, item, _reasons, result in top_n
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"=== Inbox Triage (top {args.top} of {len(results)}) ===")
    for rank, (score, item, reasons, _result) in enumerate(top_n, 1):
        reason_str = ", ".join(reasons[:3]) if reasons else "no reasons"
        print(f"{rank:2d}. [{score:.3f}] {item.title[:55]}")
        print(f"     from: {item.sender}  ({reason_str})")
    print()
    print(f"Scored {len(results)} items.")
    return 0


def _print_fold_report(report: FoldReport, args: argparse.Namespace) -> None:
    """Shared fold-report output for the demo and workspace modes."""
    if args.html:
        from pathlib import Path

        Path(args.html).write_text(report.to_html(), encoding="utf-8")
        print(f"Wrote fold report HTML to {args.html}")
        return
    if args.json:
        import json

        data = {
            "fold_id": report.fold_id,
            "timestamp": report.timestamp,
            "items_before": report.items_before,
            "items_after": report.items_after,
            "merges": len(report.merges),
            "rejected": len(report.rejected),
            "new_semantic": len(report.new_semantic),
            "recurrence_proposals": len(report.recurrence_proposals),
        }
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"=== Fold Report: {report.fold_id} ===")
        print(f"Timestamp:     {report.timestamp}")
        print(f"Items before:  {report.items_before}")
        print(f"Items after:   {report.items_after}")
        print(f"Merges:        {len(report.merges)}")
        print(f"Rejected:      {len(report.rejected)}")
        print(f"New semantic:  {len(report.new_semantic)}")
        print(f"Playbook props:{len(report.recurrence_proposals)}")


def _cmd_fold(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .fold import Folder
    from .memory import MemoryItem, MemoryStore, MemoryTier

    if args.db:
        workspace = _open_workspace(args.db)
        if workspace is None:
            return 1
        try:
            report = workspace.fold(args.now or _last_event_ts(workspace))
        finally:
            workspace.close()
        _print_fold_report(report, args)
        return 0

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    store = MemoryStore()
    for i, ev in enumerate(events):
        store.add(
            MemoryItem(
                item_id=f"mem-{i:05d}",
                tier=MemoryTier.EPISODIC,
                content=ev.payload.get("subject", ev.payload.get("title", "")),
                title=ev.payload.get("subject", ev.payload.get("title", "")),
                created_at=ev.timestamp,
            )
        )

    folder = Folder()
    last_ts = events[-1].timestamp if events else "2026-01-01T00:00:00+00:00"
    report = folder.fold(store, timestamp=last_ts)
    _print_fold_report(report, args)
    return 0


def _cmd_asof(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .temporal import IntervalFact, TemporalStore

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    store: TemporalStore[str] = TemporalStore()
    for i, ev in enumerate(events):
        fid = f"fact-{i:05d}"
        value = ev.payload.get("subject", ev.payload.get("title", ""))
        store.add(IntervalFact(fact_key=fid, value=value, valid_from=ev.timestamp))

    if args.date:
        query_date = args.date
    else:
        mid = len(events) // 2
        query_date = events[mid].timestamp[:10]

    all_keys = store.keys()
    # Gather facts valid as of query date
    valid_facts: dict[str, str] = {}
    for key in all_keys:
        fact = store.as_of(key, query_date)
        if fact is not None:
            valid_facts[key] = str(fact.value)

    print(f"=== As-of query: {query_date} ===")
    print(f"Total facts: {len(all_keys)}")
    print(f"Valid on this date: {len(valid_facts)}")
    for fid, val in list(valid_facts.items())[:10]:
        print(f"  {fid}: {val[:55]}")
    if len(valid_facts) > 10:
        print(f"  ... and {len(valid_facts) - 10} more")
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    from .context import ContextItem, ContextPacker, PackingProfile
    from .factory import WorkHistoryFactory

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    items = []
    for i, ev in enumerate(events[:100]):
        content = ev.payload.get("subject", ev.payload.get("title", str(i)))
        token_estimate = max(5, int(len(content.split()) * 1.3))
        items.append(
            ContextItem(
                item_id=ev.event_id,
                content=content,
                token_estimate=token_estimate,
                priority=round(1.0 / (i + 1), 4),
            )
        )

    profile_map = {
        "meeting_prep": PackingProfile.MEETING_PREP,
        "triage": PackingProfile.TRIAGE,
        "weekly_review": PackingProfile.WEEKLY_REVIEW,
    }
    profile = profile_map.get(args.profile, PackingProfile.MEETING_PREP)

    packer = ContextPacker(budget=args.budget, profile=profile)
    pack = packer.pack(items)

    within = pack.total_tokens <= pack.budget
    if args.json:
        import json

        payload = pack.to_dict()
        payload["within_budget"] = within
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"=== Context Pack (budget={args.budget}, profile={profile.value}) ===")
    print(f"Items packed: {len(pack.items)}")
    print(f"Tokens used:  {pack.total_tokens}")
    print(f"Within budget: {within}")
    if pack.items:
        print("\nTop items:")
        for item in pack.items[:5]:
            print(f"  [{item.token_estimate:4d} tok] {item.content[:60]}")
    return 0


def _cmd_prep(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .memory import MemoryItem, MemoryStore, MemoryTier
    from .prep import MeetingPrepper

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    store = MemoryStore()
    for ev in events:
        store.add(
            MemoryItem(
                item_id=ev.event_id,
                tier=MemoryTier.EPISODIC,
                content=ev.payload.get("body", ""),
                title=ev.payload.get("subject", ev.payload.get("title", "")),
                created_at=ev.timestamp,
            )
        )

    prepper = MeetingPrepper(store, max_items=15)
    attendees = ["alice", "bob", "carol"]
    packet = prepper.prepare(
        meeting_id=args.meeting,
        meeting_title=f"{args.meeting} prep",
        attendees=attendees,
        context_text=args.meeting,
    )

    if args.json:
        print(packet.to_json() if hasattr(packet, "to_json") else str(packet))
    else:
        print(f"=== Meeting Prep: {args.meeting} ===")
        print(f"Meeting ID: {packet.meeting_id}")
        print(f"Title: {packet.meeting_title}")
        print(f"Attendees: {', '.join(packet.attendee_names)}")
        print(f"Total items: {packet.total_items}")
        print(f"Cited sources: {len(packet.cited_sources)}")
        print(f"Agenda items: {len(packet.agenda_items)}")
        if packet.agenda_items:
            print("\nAgenda:")
            for i, item in enumerate(packet.agenda_items[:5], 1):
                print(f"  {i}. {item[:60]}")
    return 0


def _cmd_privacy(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .privacy import RedactionMode, RedactionVault, detect_pii, redact

    if args.demo:
        text = (
            "Contact alice@example.com or call 415-555-0123. "
            "Card 4532015112830366 was used at 123 Main Street, Springfield."
        )
    else:
        text = args.text or ""

    if not text and not args.demo:
        print("ERROR: provide text or use --demo", file=sys.stderr)
        return 1

    if args.unseal:
        if not args.vault:
            print("ERROR: --unseal requires --vault", file=sys.stderr)
            return 1
        vault_path = Path(args.vault)
        if not vault_path.exists():
            print(f"ERROR: vault not found: {args.vault}", file=sys.stderr)
            return 1
        print(RedactionVault.load(vault_path).unseal(text))
        return 0

    matches = detect_pii(text)
    if args.mode == "seal":
        if not args.vault:
            print("ERROR: seal mode requires --vault", file=sys.stderr)
            return 1
        vault_path = Path(args.vault)
        vault = (
            RedactionVault.load(vault_path)
            if vault_path.exists()
            else RedactionVault(salt=args.salt)
        )
        sealed = vault.seal(text)
        vault.save(vault_path)
        print("=== Privacy Scan ===")
        print(f"Found {len(matches)} PII matches; vault now holds {vault.sealed_count()} token(s)")
        print()
        print("Sealed (reversible only via the vault):")
        print(sealed)
        return 0

    mode_map = {
        "mask": RedactionMode.MASK,
        "hash": RedactionMode.HASH,
        "remove": RedactionMode.REMOVE,
    }
    mode = mode_map[args.mode]
    redacted = redact(text, matches, mode=mode, hash_salt=args.salt)

    print("=== Privacy Scan ===")
    print(f"Found {len(matches)} PII matches:")
    kind_counts: dict[str, int] = {}
    for m in matches:
        kind_counts[m.kind.value] = kind_counts.get(m.kind.value, 0) + 1
    for kind, count in sorted(kind_counts.items()):
        print(f"  {kind}: {count}")
    print()
    print(f"Redacted ({mode.value} mode):")
    print(redacted)
    return 0


def _cmd_triggers(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .triggers import (
        TriggerEngine,
        TriggerKind,
        TriggerRule,
        TriggerSeverity,
        derive_followup_rules,
        derive_stale_thread_rules,
    )

    if args.db:
        workspace = _open_workspace(args.db)
        if workspace is None:
            return 1
        try:
            now_text = args.now or _last_event_ts(workspace)
            moment = _parse_ts(now_text)
            journal_events = list(workspace.journal.iter_events())
            # commitment rules run through the workspace (receipted tick),
            # thread rules derive from journal events and join the engine
            fired = workspace.triggers_tick(now_text)
            derived = derive_stale_thread_rules(journal_events, moment)
            derived += derive_followup_rules(journal_events, moment)
            for rule in derived:
                workspace.trigger_engine.add_rule(rule)
            fired = fired + workspace.trigger_engine.tick(moment)
        finally:
            workspace.close()
    else:
        factory = WorkHistoryFactory(seed=args.seed, days=args.days)
        events, _manifest = factory.generate()

        if not events:
            print("No events generated.")
            return 0

        engine = TriggerEngine()
        now = _parse_ts(events[-1].timestamp)
        # Create sample triggers for planted commitments
        planted = [p for p in factory.planted_items() if p.kind == "commitment"]
        for i, item in enumerate(planted):
            engine.add_rule(
                TriggerRule(
                    rule_id=f"deadline-{i}",
                    kind=TriggerKind.DEADLINE_REMINDER,
                    target_id=item.item_id,
                    fire_at=_parse_ts(item.data["due_date"]),
                    severity=TriggerSeverity.WARNING,
                    message=f"Deadline approaching: {item.data['description'][:40]}",
                )
            )

        fired = engine.tick(now)

    active = [f for f in fired if not f.suppressed]

    if args.json:
        import json

        data = [
            {
                "rule_id": f.rule_id,
                "kind": f.kind.value,
                "target_id": f.target_id,
                "severity": f.severity.value,
                "message": f.message,
                "suppressed": f.suppressed,
                "suppress_reason": f.suppress_reason,
            }
            for f in fired
        ]
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print("=== Proactive Triggers ===")
        print(f"Total fired: {len(fired)}")
        print(f"Active: {len(active)}")
        print(f"Suppressed: {len(fired) - len(active)}")
        print()
        for f in active[:10]:
            print(f"  [{f.severity.value:4s}] {f.kind.value}: {f.message[:55]}")
        if len(active) > 10:
            print(f"  ... and {len(active) - 10} more")

    return 0


def _parse_ts(raw: str) -> datetime:
    """Parse an ISO timestamp, assuming UTC when naive (e.g. bare dates)."""
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _open_workspace(db: str) -> Workspace | None:
    """Open an existing workspace, or report and return None if absent."""
    from pathlib import Path

    from .workspace import Workspace

    if not Path(db).exists():
        print(f"ERROR: workspace not found: {db} (run 'ingest' first)", file=sys.stderr)
        return None
    return Workspace(db)


def _cmd_ingest(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .workspace import Workspace

    if args.jsonl:
        from .events import Event

        path = Path(args.jsonl)
        if not path.exists():
            print(f"ERROR: jsonl file not found: {args.jsonl}", file=sys.stderr)
            return 1
        events = [
            Event.from_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        source = args.jsonl
    else:
        from .factory import WorkHistoryFactory

        factory = WorkHistoryFactory(seed=args.seed, days=args.days)
        synthetic, _manifest = factory.generate()
        events = [e.to_event() for e in synthetic]
        source = f"synthetic seed={args.seed} days={args.days}"

    workspace = Workspace(args.db)
    try:
        added = workspace.ingest_events(events)
        stats = workspace.stats()
    finally:
        workspace.close()

    print("=== mnemofold ingest ===")
    print(f"Source: {source}")
    print(f"Workspace: {args.db}")
    print(f"Ingested: {added} new events")
    print(f"Events: {stats.events}  Memories: {stats.memories}  Commitments: {stats.commitments}")
    print(f"Digest: {stats.digest}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    if args.bundle:
        try:
            manifest = workspace.export_bundle(args.bundle)
        finally:
            workspace.close()
        print(f"Wrote workspace bundle to {args.bundle}")
        print(
            f"  events={manifest['events']} memories={manifest['memories']} "
            f"commitments={manifest['commitments']} tombstones={manifest['tombstones']}"
        )
        return 0
    try:
        stats = workspace.stats()
        if args.format == "json":
            payload = {
                "stats": {
                    "events": stats.events,
                    "memories": stats.memories,
                    "commitments": stats.commitments,
                    "tombstones": stats.tombstones,
                    "head_checksum": stats.head_checksum,
                    "digest": stats.digest,
                },
                "ledger": json.loads(workspace.ledger.to_json()),
            }
            text = json.dumps(payload, indent=2, sort_keys=True)
        else:
            text = workspace.ledger.to_markdown()
    finally:
        workspace.close()

    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.format} export to {args.out}")
    else:
        print(text)
    return 0


def _cmd_remember(args: argparse.Namespace) -> int:
    from .workspace import Workspace

    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    try:
        workspace = Workspace(args.db)
        try:
            item_id = workspace.remember(args.text, now=args.now, title=args.title, tags=tags)
        finally:
            workspace.close()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"remembered {item_id}")
    return 0


def _cmd_forget(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    if args.preview:
        preview = workspace.forget_preview(args.item_id)
        workspace.close()
        print(f"preview for {args.item_id}:")
        print(f"  would delete: {preview['total']} item(s)")
        for entry in preview["would_delete"]:
            print(f"    - {entry['key']} ({entry['kind']}, depth {entry['depth']})")
        if preview["blocked"]:
            print(f"  blocked (protected): {', '.join(preview['blocked'])}")
        if preview["missing"]:
            print(f"  missing: {', '.join(preview['missing'])}")
        if preview["ledger_commitments_affected"]:
            affected = ", ".join(preview["ledger_commitments_affected"])
            print(f"  ledger commitments affected: {affected}")
        print("nothing was deleted (preview only)")
        return 0
    try:
        report = workspace.forget(args.item_id, now=args.now, reason=args.reason)
    except ValueError as exc:
        workspace.close()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    workspace.close()
    if report.total_deleted == 0 and report.errors:
        print(f"ERROR: {args.item_id}: {'; '.join(report.errors)}", file=sys.stderr)
        return 1
    if args.report == "json":
        print(report.to_json())
    elif args.report == "markdown":
        print(report.to_markdown())
    else:
        print(f"forgotten {report.total_deleted} item(s); tombstone recorded")
    return 0


def _cmd_recall(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    item = workspace.recall(args.item_id)
    workspace.close()
    if item is None:
        print(f"ERROR: no live memory for {args.item_id}", file=sys.stderr)
        return 1
    print(f"id: {item.item_id}")
    print(f"tier: {item.tier.value}")
    print(f"title: {item.title}")
    print(f"created: {item.created_at}")
    if item.tags:
        print(f"tags: {', '.join(sorted(item.tags))}")
    print(item.content)
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from .retrieval import parse_query

    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    try:
        results = workspace.ask(args.query, top_k=args.top, as_of=args.as_of)
        explanations: dict[str, list[dict[str, object]]] | None = None
        if args.explain:
            free_text = parse_query(args.query).text
            explanations = {}
            for r in results:
                explanations[r.item_id] = [
                    {
                        "term": c.term,
                        "tf": c.tf,
                        "df": c.df,
                        "idf": round(c.idf, 6),
                        "contribution": round(c.contribution, 6),
                    }
                    for c in workspace.engine.index.explain(free_text, r.item_id)
                ]
    finally:
        workspace.close()
    if args.json:
        import json

        payload = [
            {
                "item_id": r.item_id,
                "score": round(r.score, 6),
                "title": r.title,
                "citation": r.citation,
                **({"explain": explanations[r.item_id]} if explanations is not None else {}),
            }
            for r in results
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"=== {len(results)} result(s) for: {args.query} ===")
        for rank, r in enumerate(results, 1):
            print(f"{rank:2d}. [{r.score:.3f}] {r.title[:60]} {r.citation}")
            if explanations is not None:
                for c in explanations[r.item_id]:
                    print(
                        f"      term {str(c['term'])!r}: tf={c['tf']} df={c['df']} "
                        f"idf={c['idf']} -> {c['contribution']}"
                    )
    return 0


def _last_event_ts(workspace: Workspace) -> str:
    """Timestamp of the most recent journal event (epoch fallback)."""
    for event in workspace.journal.iter_events(reverse=True):
        return event.timestamp.isoformat()
    return "1970-01-01T00:00:00+00:00"


def _cmd_standup(args: argparse.Namespace) -> int:
    from .review import StandupGenerator, render_standup_html, render_standup_markdown

    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    try:
        today = args.today or _last_event_ts(workspace)
        try:
            data = StandupGenerator(workspace.ledger).generate(today)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    finally:
        workspace.close()
    if args.json:
        import json

        print(json.dumps(data.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_standup_html(data) if args.html else render_standup_markdown(data))
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    from datetime import date as date_cls

    from .review import WeeklyReviewGenerator, render_weekly_html, render_weekly_markdown

    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    try:
        review = WeeklyReviewGenerator(workspace.ledger).generate(args.start, args.end)
        try:
            days = max(
                1,
                (
                    date_cls.fromisoformat(args.end[:10]) - date_cls.fromisoformat(args.start[:10])
                ).days,
            )
            series = workspace.ledger.burndown_series(args.start[:10], days)
        except ValueError:
            print(
                "ERROR: --start/--end must begin with ISO dates (YYYY-MM-DD)",
                file=sys.stderr,
            )
            return 1
    finally:
        workspace.close()
    if args.json:
        import json

        print(json.dumps(review.to_dict(), indent=2, sort_keys=True))
    elif args.html:
        print(render_weekly_html(review, series))
    else:
        print(render_weekly_markdown(review))
    return 0


def _cmd_playbooks(args: argparse.Namespace) -> int:
    from .fold import Folder

    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    try:
        folder = Folder(min_episodes_for_recurrence=args.min_repeats)
        report = folder.fold(workspace.store, _last_event_ts(workspace))
    finally:
        workspace.close()
    proposals = report.recurrence_proposals
    if args.json:
        import json

        print(json.dumps(proposals, indent=2, sort_keys=True))
    else:
        print(f"=== {len(proposals)} playbook proposal(s) ===")
        for proposal in proposals[:20]:
            if proposal.get("kind") == "workflow_sequence":
                steps = " -> ".join(proposal["steps"])
                print(
                    f"- workflow '{proposal['workflow']}': {steps} ({proposal['run_count']} runs)"
                )
            else:
                print(
                    f"- tag '{proposal.get('pattern_tag')}': "
                    f"{proposal.get('instance_count')} instances"
                )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the mnemofold CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_verify(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from .workspace import Workspace

    if not Path(args.db).is_dir():
        print(f"ERROR: workspace not found: {args.db}", file=sys.stderr)
        return 1

    workspace = Workspace(args.db)
    try:
        report = workspace.verify_integrity()
    finally:
        workspace.close()

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("=== mnemofold verify ===")
        for name in sorted(report["checks"]):
            mark = "ok" if report["checks"][name] else "FAILED"
            print(f"  {name}: {mark}")
        print(f"Frames checked: {report['frames_checked']}")
        print(f"Tombstones: {report['tombstones']}")
        print(f"Result: {'PASS' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


def _cmd_decay(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args.db)
    if workspace is None:
        return 1
    try:
        counters = workspace.apply_decay(args.now)
    finally:
        workspace.close()
    if args.json:
        import json

        print(json.dumps(counters, indent=2, sort_keys=True))
    else:
        print("=== Decay pass ===")
        for key in sorted(counters):
            print(f"  {key}: {counters[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
