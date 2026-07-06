"""Example: a full assistant week on synthetic history.

Fully offline: builds a persistent workspace from three weeks of
synthetic history, then runs the assistant duties against it — inbox
triage with batching, cited meeting prep, a standup report, a weekly
review rendered to self-contained HTML, an assembled report page with a
commitment timeline, and a budgeted context pack. It finishes with the
evaluation suite scorecard measured against planted ground truth.

All artifacts are written inside a temporary directory that is removed
on exit; nothing else touches disk and no network is used.

Run:
    python examples/assistant_week/run.py
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

from mnemofold.context import ContextItem, ContextPacker, PackingProfile, estimate_tokens
from mnemofold.evaluation import ScenarioConfig, run_role_slices, run_suite
from mnemofold.factory import WorkHistoryFactory
from mnemofold.ingest import CommitmentExtractor
from mnemofold.prep import MeetingPrepper
from mnemofold.reports import TimelineItem, assemble_report_page
from mnemofold.review import (
    StandupGenerator,
    WeeklyReviewGenerator,
    render_standup_markdown,
    render_weekly_html,
)
from mnemofold.triage import TriageBatcher, TriageItem, TriageScorer
from mnemofold.workspace import Workspace

SEED = 9
DAYS = 21


def main() -> int:
    factory = WorkHistoryFactory(seed=SEED, days=DAYS)
    synthetic, manifest = factory.generate()
    typed = [event.to_event() for event in synthetic]
    now = typed[-1].timestamp.isoformat()
    last_day = typed[-1].timestamp

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Workspace(Path(tmp) / "week")
        try:
            workspace.ingest_events(typed, now=now)
            stats = workspace.stats()

            # 1. Inbox triage over mail/chat, then deterministic batching.
            extractor = CommitmentExtractor()
            scorer = TriageScorer()
            items: list[TriageItem] = []
            for event in typed:
                if event.event_type.value not in (
                    "mail_received",
                    "mail_sent",
                    "chat_message",
                ):
                    continue
                content = event.content
                mentions = extractor.extract(event)
                due = next((m.due for m in mentions if m.due), None)
                items.append(
                    TriageItem(
                        item_id=event.event_id,
                        title=str(content.get("subject", content.get("channel", ""))),
                        sender=str(content.get("sender", content.get("persona_id", ""))),
                        received_at=event.timestamp.isoformat(),
                        content=str(content.get("body", content.get("text", ""))),
                        mentions_commitment=bool(mentions),
                        has_deadline=due is not None,
                        deadline=f"{due}T00:00:00+00:00" if due else "",
                    )
                )
            ranked = scorer.batch_score(items, now)
            plan = TriageBatcher(max_act_now=3, max_review=8).batch(ranked)

            # 2. Meeting prep from workspace memories (cited packet).
            prepper = MeetingPrepper(store=workspace.store, max_items=10)
            packet = prepper.prepare(
                meeting_id="weekly-sync",
                meeting_title="Weekly alpha sync",
                attendees=["p1", "p2"],
                context_text="alpha milestone update",
            )

            # 3. Standup (markdown) and weekly review (self-contained HTML).
            standup_md = render_standup_markdown(StandupGenerator(workspace.ledger).generate(now))
            review = WeeklyReviewGenerator(workspace.ledger).generate(
                (last_day - timedelta(days=7)).isoformat(), now
            )
            review_html = render_weekly_html(review)
            (Path(tmp) / "weekly_review.html").write_text(review_html, encoding="utf-8")

            # 4. Assembled report page: commitment timeline + workload strip.
            timeline: list[TimelineItem] = []
            for commitment in workspace.ledger.all_commitments():
                if not commitment.due_date:
                    continue
                due = date.fromisoformat(commitment.due_date[:10])
                status = "overdue" if commitment.is_overdue(now) else "open"
                timeline.append(
                    TimelineItem(
                        label=commitment.description,
                        start=due - timedelta(days=7),
                        end=due,
                        status=status,
                    )
                )
            day_counts = [0] * DAYS
            start_day = factory.start_date.date()
            for event in typed:
                index = (event.timestamp.date() - start_day).days
                if 0 <= index < DAYS:
                    day_counts[index] += 1
            page = assemble_report_page(
                "Assistant week",
                timeline_items=timeline,
                day_counts=day_counts,
                run_metadata={
                    "seed": str(SEED),
                    "days": str(DAYS),
                    "checksum": manifest.checksum,
                },
            )

            # 5. Budgeted context pack for the meeting.
            pack = ContextPacker(budget=600, profile=PackingProfile.MEETING_PREP).pack(
                [
                    ContextItem(
                        item_id=item.item_id,
                        content=item.summary,
                        title=item.title,
                        token_estimate=estimate_tokens(item.summary),
                        priority=item.priority,
                    )
                    for item in packet.items
                ]
            )
        finally:
            workspace.close()

    # 6. Evaluation suite against planted ground truth (synthetic only).
    suite = run_suite(ScenarioConfig(seed=SEED, days=DAYS))
    aggregate = {m.name: m.value for m in suite.aggregate.metrics}
    role_slices = run_role_slices(ScenarioConfig(seed=SEED, days=DAYS))
    role_recalls = {
        result.scorecard.scenario: {m.name: m.value for m in result.scorecard.metrics}
        for result in role_slices
    }

    print("=== assistant_week: full offline assistant loop ===")
    print(f"seed={SEED} days={DAYS} checksum={manifest.checksum}")
    print(
        f"workspace: events={stats.events} memories={stats.memories} "
        f"commitments={stats.commitments}"
    )
    print(
        f"triage: ranked={len(ranked)} act_now={len(plan.act_now)} "
        f"review={len(plan.review)} defer={len(plan.defer)}"
    )
    print(
        f"prep: items={packet.total_items} agenda={len(packet.agenda_items)} "
        f"citations={len(packet.cited_sources)}"
    )
    print(f"standup markdown chars: {len(standup_md)}")
    print(f"weekly review html bytes: {len(review_html)}")
    print(f"report page bytes: {len(page)} (timeline items: {len(timeline)})")
    print(f"context pack: {len(pack.items)} items, {pack.total_tokens}/{pack.budget} tokens")
    print(f"suite overall_pass: {suite.overall_pass()}")
    for name in sorted(aggregate):
        print(f"  aggregate {name}: {aggregate[name]:.4f}")
    for scenario in sorted(role_recalls):
        recall = role_recalls[scenario].get("role_commitment_recall", 0.0)
        print(f"  role slice {scenario}: recall={recall:.4f}")

    ok = (
        stats.memories > 0
        and plan.total() == len(ranked)
        and packet.total_items > 0
        and pack.total_tokens <= pack.budget
        and suite.overall_pass()
        and all(result.scorecard.overall_pass() for result in role_slices)
    )
    print(f"RESULT: {'OK' if ok else 'CHECK FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
