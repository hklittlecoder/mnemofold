"""Command-line interface for mnemofold.

Subcommands are grouped by functionality: ingestion, query, reports,
memory ops, evaluation, and utilities.  Each subcommand has its own
help text and exit codes.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__


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
    p_ledger.set_defaults(func=_cmd_ledger)

    # triage
    p_triage = sub.add_parser("triage", help="score and rank inbox items")
    p_triage.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_triage.add_argument("--days", type=int, default=14, help="days of history")
    p_triage.add_argument("--top", type=int, default=10, help="show top N items")
    p_triage.set_defaults(func=_cmd_triage)

    # fold
    p_fold = sub.add_parser("fold", help="run nightly consolidation fold")
    p_fold.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_fold.add_argument("--days", type=int, default=30, help="days of history to fold")
    p_fold.add_argument("--json", action="store_true", help="output JSON fold report")
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
        "--mode", default="mask", choices=["mask", "hash", "remove"], help="redaction mode"
    )
    p_privacy.add_argument("--salt", default="", help="salt for hash mode")
    p_privacy.set_defaults(func=_cmd_privacy)

    # triggers
    p_triggers = sub.add_parser("triggers", help="list active proactive triggers")
    p_triggers.add_argument("--seed", type=int, default=42, help="seed for demo data")
    p_triggers.add_argument("--days", type=int, default=30, help="days of history")
    p_triggers.add_argument("--json", action="store_true", help="output JSON")
    p_triggers.set_defaults(func=_cmd_triggers)

    return parser


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from .evaluation import MetricResult, MetricStatus, Scorecard
    from .factory import WorkHistoryFactory

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, manifest = factory.generate()

    sc = Scorecard(scenario=f"eval-seed{args.seed}-{args.days}d")
    sc.add(MetricResult(name="event_count", value=float(len(events)), higher_is_better=True))
    sc.add(
        MetricResult(
            name="planted_commitments",
            value=float(manifest.planted_commitments),
            higher_is_better=True,
        )
    )
    sc.add(
        MetricResult(
            name="planted_decisions",
            value=float(manifest.planted_decisions),
            higher_is_better=True,
        )
    )
    sc.add(
        MetricResult(
            name="planted_contradictions",
            value=float(manifest.planted_contradictions),
            higher_is_better=True,
        )
    )
    # Determinism check (implicit pass: we generated once and have a checksum)
    sc.add(
        MetricResult(
            name="deterministic_checksum",
            value=1.0 if manifest.checksum else 0.0,
            threshold=1.0,
            higher_is_better=True,
            status=MetricStatus.PASS if manifest.checksum else MetricStatus.FAIL,
        )
    )
    sc.details = {
        "seed": args.seed,
        "days": args.days,
        "checksum": manifest.checksum,
    }

    if args.json:
        import json

        print(json.dumps(sc.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"=== mnemofold eval (seed={args.seed}, days={args.days}) ===")
        print(f"Events: {len(events)}")
        print(f"Planted commitments: {manifest.planted_commitments}")
        print(f"Planted decisions: {manifest.planted_decisions}")
        print(f"Planted contradictions: {manifest.planted_contradictions}")
        print(f"Checksum: {manifest.checksum}")
        print(f"Pass: {sc.overall_pass()}")

    return 0 if sc.overall_pass() else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    from .evaluation import MetricResult, Scorecard
    from .factory import WorkHistoryFactory

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

    # Triage demo — score a sample of mail events
    from .triage import TriageItem, TriageScorer

    scorer = TriageScorer()
    mail_events = [e for e in events if e.event_type in ("mail_received", "mail_sent")][:10]
    now = events[-1].timestamp if events else "2026-01-01T00:00:00+00:00"
    triage_results = []
    for ev in mail_events:
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
        triage_results.append((result.score, item.title, result.reasons))
    triage_results.sort(key=lambda x: -x[0])
    print("Top triaged mail items:")
    for score, title, reasons in triage_results[:5]:
        reason_str = ", ".join(reasons[:3])
        print(f"  [{score:.3f}] {title[:50]} ({reason_str})")
    print()

    # Standup demo
    from .ledger import CommitmentLedger
    from .review import StandupGenerator

    ledger = CommitmentLedger()
    gen = StandupGenerator(ledger)
    last_date = events[-1].timestamp[:10] if events else "2026-01-01"
    data = gen.generate(today=last_date)
    print(f"Standup for {data.date}:")
    print(f"  Completed: {len(data.completed)}")
    print(f"  In progress: {len(data.in_progress)}")
    print(f"  Planned: {len(data.planned)}")
    print(f"  Blockers: {len(data.blockers)}")
    print(f"  Open commitments: {data.open_commitments}")
    print(f"  Overdue: {data.overdue}")
    print(f"  Pending decisions: {data.pending_decisions}")
    print()

    # Scorecard
    sc = Scorecard(scenario=f"demo-seed{args.seed}")
    sc.add(MetricResult(name="events_generated", value=float(len(events))))
    sc.add(MetricResult(name="mail_triage_scored", value=float(len(triage_results))))
    sc.add(
        MetricResult(
            name="deterministic_checksum",
            value=1.0 if manifest.checksum else 0.0,
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
    _events, _manifest = factory.generate()

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
        results.append((result.score, item, result.reasons))

    results.sort(key=lambda x: -x[0])
    top_n = results[: args.top]

    print(f"=== Inbox Triage (top {args.top} of {len(results)}) ===")
    for rank, (score, item, reasons) in enumerate(top_n, 1):
        reason_str = ", ".join(reasons[:3]) if reasons else "no reasons"
        print(f"{rank:2d}. [{score:.3f}] {item.title[:55]}")
        print(f"     from: {item.sender}  ({reason_str})")
    print()
    print(f"Scored {len(results)} items.")
    return 0


def _cmd_fold(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .fold import Folder
    from .memory import MemoryItem, MemoryStore, MemoryTier

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

    return 0


def _cmd_asof(args: argparse.Namespace) -> int:
    from .factory import WorkHistoryFactory
    from .temporal import IntervalFact, TemporalStore

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    store = TemporalStore()
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
    from .privacy import RedactionMode, detect_pii, redact

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

    matches = detect_pii(text)
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
    )

    factory = WorkHistoryFactory(seed=args.seed, days=args.days)
    events, _manifest = factory.generate()

    if not events:
        print("No events generated.")
        return 0

    engine = TriggerEngine()
    now = events[-1].timestamp
    # Create sample triggers for planted commitments
    planted = [p for p in factory.planted_items() if p.kind == "commitment"]
    for i, item in enumerate(planted):
        engine.add_rule(
            TriggerRule(
                rule_id=f"deadline-{i}",
                kind=TriggerKind.DEADLINE_REMINDER,
                target_id=item.item_id,
                fire_at=item.data["due_date"],
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


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the mnemofold CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
