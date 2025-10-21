"""Persistent workspace: journal-backed memory, ledger, and retrieval.

A workspace directory ties the durable spine (the hash-chained SQLite
journal) to the derived projections (memory store, retrieval index,
commitment ledger) and the replay trace. The journal is the only source
of truth: every projection is rebuilt from it on open, and rebuilding
twice must produce an identical digest. Tombstones recorded in the
journal block re-derivation of forgotten events, so deletion survives
rebuilds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemofold.context import (
    ContextItem,
    ContextPack,
    ContextPacker,
    PackingProfile,
    estimate_tokens,
)
from mnemofold.decay import DecayEngine
from mnemofold.deletion import DeletionEngine, DeletionReason, DeletionReport
from mnemofold.events import Event, EventType
from mnemofold.fold import Folder, FoldReport
from mnemofold.ingest import CommitmentExtractor
from mnemofold.ledger import Commitment, CommitmentLedger
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.prep import MeetingPrep, MeetingPrepper
from mnemofold.replay import TraceRecorder
from mnemofold.retrieval import (
    RetrievalEngine,
    SearchResult,
    build_deletion_engine,
    parse_query,
)
from mnemofold.retrieval import (
    forget as forget_item,
)
from mnemofold.review import StandupData, StandupGenerator, WeeklyReview, WeeklyReviewGenerator
from mnemofold.storage import Journal
from mnemofold.triage import BatchPlan, TriageBatcher, TriageItem, TriageResult, TriageScorer
from mnemofold.triggers import FiredTrigger, TriggerEngine, derive_commitment_rules


@dataclass(slots=True)
class WorkspaceStats:
    """Snapshot counters for a workspace."""

    events: int
    memories: int
    commitments: int
    tombstones: int
    head_checksum: str
    digest: str


def _parse_now(now: str) -> datetime:
    try:
        moment = datetime.fromisoformat(now)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid timestamp: {now!r}") from exc
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def project_event(event: Event) -> MemoryItem:
    """Deterministic projection of one event into an episodic memory.

    The item always carries its event type as a tag; string ``tags``
    lists in the payload (user labels, factory workflow tags) are merged
    in so tag filters and recurrence mining can see them.
    """
    parts = [str(v) for _k, v in sorted(event.content.items()) if isinstance(v, str) and v]
    text = " ".join(parts) or str(event.event_type.value)
    title = str(
        event.content.get("subject") or event.content.get("title") or event.event_type.value
    )
    tags = {event.event_type.value}
    content_tags = event.content.get("tags")
    if isinstance(content_tags, list):
        tags.update(str(tag) for tag in content_tags if isinstance(tag, str) and tag)
    return MemoryItem(
        item_id=event.event_id,
        tier=MemoryTier.EPISODIC,
        content=text,
        title=title,
        created_at=event.timestamp.isoformat(),
        tags=tags,
        metadata={"event_type": event.event_type.value},
    )


class Workspace:
    """Journal-backed workspace with memory, ledger, and retrieval views.

    Lifecycle: ``Workspace(path)`` opens (and rebuilds projections from)
    the journal at ``path``. Mutations (``ingest_events``, ``remember``,
    ``forget``) append to the journal first, then update projections, and
    are mirrored into the replay trace so a session can be replayed
    byte-identically. ``close()`` releases the journal and trace files.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.journal = Journal(self.path / "journal.db")
        self.trace = TraceRecorder(self.path / "trace.jsonl")
        self.store = MemoryStore()
        self.engine = RetrievalEngine(store=self.store)
        self.deletion: DeletionEngine = build_deletion_engine(self.engine)
        self.ledger = CommitmentLedger()
        self._extractor = CommitmentExtractor()
        self.decay_engine = DecayEngine()
        self.trigger_engine = TriggerEngine()
        self.rebuild()

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self.journal.close()
        self.trace.close()

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- projection ----------------------------------------------------------

    def _is_tombstoned(self, event_id: str) -> bool:
        return self.journal.tombstone(event_id) is not None or self.deletion.is_deleted(event_id)

    def _project_one(self, event: Event) -> None:
        item = project_event(event)
        self.store.add(item)
        self.engine.index_item(item)
        for mention in self._extractor.extract(event):
            if mention.evidence.field != "commitment_ref":
                continue
            ref = mention.evidence.quote
            if self.ledger.get(ref) is not None:
                continue
            due = f"{mention.due}T00:00:00+00:00" if mention.due else ""
            self.ledger.add(
                Commitment(
                    commitment_id=ref,
                    owed_by=mention.debtor,
                    owed_to=mention.creditor,
                    description=mention.description,
                    due_date=due,
                    created_at=event.timestamp.isoformat(),
                    source_event_ids=[event.event_id],
                )
            )

    def rebuild(self) -> WorkspaceStats:
        """Re-project every view from the journal (idempotent).

        Tombstoned events are skipped, so forgetting survives rebuilds:
        the journal keeps the frame (the chain stays verifiable) but the
        projections never re-derive it.
        """
        self.store = MemoryStore()
        self.engine = RetrievalEngine(store=self.store)
        self.deletion = build_deletion_engine(self.engine)
        self.ledger = CommitmentLedger()
        for event in self.journal.iter_events():
            if self._is_tombstoned(event.event_id):
                continue
            self._project_one(event)
        return self.stats()

    def projection_digest(self) -> str:
        """SHA-256 over the canonical projection state (rebuild identity)."""
        items = []
        for tier in MemoryTier:
            for item in self.store.items_by_tier(tier):
                items.append([item.item_id, str(item.tier)])
        items.sort()
        payload = {
            "items": items,
            "commitments": sorted(c.commitment_id for c in self.ledger.all_commitments()),
            "indexed": self.engine.index.ids(),
            "head": self.journal.head_checksum(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def stats(self) -> WorkspaceStats:
        return WorkspaceStats(
            events=len(self.journal),
            memories=self.store.total_count(),
            commitments=self.ledger.total_count(),
            tombstones=len(list(self.journal.iter_tombstones())),
            head_checksum=self.journal.head_checksum(),
            digest=self.projection_digest(),
        )

    def snapshot(self) -> dict[str, Any]:
        """Serializable point-in-time view of every projection.

        Groups memory ids by tier and lists ledger statuses, tombstones,
        and the journal head so two snapshots can be diffed after an
        import, a fold, or a rebuild. Side-effect free: projections are
        read without touching access statistics.
        """
        return {
            "memories": {
                tier.value: sorted(item.item_id for item in self.store.items_by_tier(tier))
                for tier in MemoryTier
            },
            "commitments": {
                c.commitment_id: c.status.value
                for c in sorted(self.ledger.all_commitments(), key=lambda c: c.commitment_id)
            },
            "tombstones": sorted(t.event_id for t in self.journal.iter_tombstones()),
            "head": self.journal.head_checksum(),
            "digest": self.projection_digest(),
        }

    # -- mutations -----------------------------------------------------------

    def ingest_events(self, events: list[Event], now: str = "") -> int:
        """Append events to the journal and project the new ones.

        Duplicate events (already journaled) are skipped; tombstoned ids
        are journaled but never projected. Returns the number of newly
        appended frames.
        """
        stamp = now or (events[-1].timestamp.isoformat() if events else "")
        added = 0
        for event in events:
            fresh = self.journal.append(event)
            if fresh:
                added += 1
                self.trace.record_event(
                    event.timestamp.isoformat(),
                    {"event_id": event.event_id, "type": event.event_type.value},
                )
            if not self._is_tombstoned(event.event_id) and self.store.peek(event.event_id) is None:
                self._project_one(event)
        if stamp:
            self.trace.record_receipt(stamp, {"action": "ingest", "added": added})
        return added

    def fold(self, timestamp: str, *, similarity_threshold: float = 0.75) -> FoldReport:
        """Run one deterministic folding pass over projected memories.

        Folding is a derived view: the journal keeps the raw events, so
        a rebuild re-projects episodes and re-folding with the same
        timestamp reproduces the same report digest. The receipt (fold
        id and digest) is mirrored into the trace, letting a replay
        verify that consolidation happened identically.
        """
        folder = Folder(similarity_threshold=similarity_threshold)
        report = folder.fold(self.store, timestamp)
        self.trace.record_receipt(
            timestamp,
            {"action": "fold", "fold_id": report.fold_id, "digest": report.digest()},
        )
        return report

    def apply_decay(self, now: str) -> dict[str, int]:
        """Apply per-tier retention decay to the projected memories.

        Pinned items, legal-hold tags, and engine holds are protected
        (see :class:`DecayEngine`). Decay mutates only the derived
        projections, never the journal; the counters are receipted into
        the trace for replay audits.
        """
        stats = self.decay_engine.apply_decay(self.store, now)
        self.trace.record_receipt(now, {"action": "decay", **stats})
        return stats

    def triage(
        self,
        items: list[TriageItem],
        now: str,
        *,
        max_act_now: int = 3,
        max_review: int = 10,
    ) -> tuple[list[TriageResult], BatchPlan]:
        """Score inbox items and route them through the batching rules.

        Scoring is deterministic for a given ``now``; the batch plan
        conserves every scored item across act_now/review/defer. Batch
        totals are receipted into the trace so a replay can confirm the
        same routing happened.
        """
        results = TriageScorer().batch_score(items, now)
        plan = TriageBatcher(max_act_now=max_act_now, max_review=max_review).batch(results)
        self.trace.record_receipt(
            now,
            {
                "action": "triage",
                "scored": len(results),
                "act_now": len(plan.act_now),
                "review": len(plan.review),
                "defer": len(plan.defer),
            },
        )
        return results, plan

    def context_pack(
        self,
        query: str,
        *,
        budget_tokens: int,
        top_k: int = 10,
        profile: PackingProfile = PackingProfile.GENERAL,
        now: str = "",
    ) -> ContextPack:
        """Retrieve candidates and pack them under a token budget.

        Candidates come from the live retrieval engine, so every packed
        item cites a non-forgotten memory. Selection is the exact 0/1
        knapsack DP: the pack never exceeds ``budget_tokens``.
        """
        results = self.engine.search_parsed(parse_query(query), top_k=top_k)
        items = [
            ContextItem(
                item_id=result.item_id,
                content=result.snippet or result.title,
                title=result.title,
                token_estimate=estimate_tokens(result.snippet or result.title),
                priority=result.score,
            )
            for result in results
        ]
        pack = ContextPacker(budget=budget_tokens, profile=profile).pack(items)
        if now:
            self.trace.record_receipt(
                now,
                {
                    "action": "context",
                    "query": query,
                    "items": len(pack),
                    "tokens": pack.total_tokens,
                },
            )
        return pack

    def prep(
        self,
        meeting_id: str,
        meeting_title: str,
        attendees: list[str],
        *,
        context_text: str = "",
        now: str = "",
    ) -> MeetingPrep:
        """Assemble a cited meeting-prep packet from projected memories.

        Citations in the packet always resolve to live workspace
        memories; the receipt records the packet size so replays can
        confirm the same evidence was gathered.
        """
        packet = MeetingPrepper(store=self.store).prepare(
            meeting_id, meeting_title, attendees, context_text
        )
        if now:
            self.trace.record_receipt(
                now,
                {
                    "action": "prep",
                    "meeting_id": meeting_id,
                    "items": packet.total_items,
                },
            )
        return packet

    def standup(
        self,
        today: str,
        *,
        pending_decisions: list[str] | None = None,
        now: str = "",
    ) -> StandupData:
        """Generate today's standup snapshot from the journaled ledger.

        Commitments extracted at ingest time feed the open and overdue
        lists; every report line cites its commitment id.
        """
        data = StandupGenerator(ledger=self.ledger).generate(today, pending_decisions)
        if now:
            self.trace.record_receipt(
                now,
                {
                    "action": "standup",
                    "date": today,
                    "open": len(data.open_commitments),
                    "overdue": len(data.overdue),
                },
            )
        return data

    def weekly_review(self, week_start: str, week_end: str, *, now: str = "") -> WeeklyReview:
        """Generate the weekly roll-up from ledger transition history.

        ``completed`` reflects transitions inside ``[week_start,
        week_end)``; overdue and open lists are evaluated as of
        ``week_end``. Every line cites its commitment id.
        """
        review = WeeklyReviewGenerator(ledger=self.ledger).generate(week_start, week_end)
        if now:
            self.trace.record_receipt(
                now,
                {
                    "action": "review",
                    "week_start": week_start,
                    "completed": len(review.completed),
                    "overdue": len(review.overdue),
                },
            )
        return review

    def triggers_tick(self, now: str, *, ahead_days: float = 2.0) -> list[FiredTrigger]:
        """Derive commitment triggers and tick the engine once.

        Rules are re-derived on every call so they track ledger changes
        without persistent state; rule ids are stable per commitment and
        the session engine keeps cooldown/dedupe memory across calls.
        Fired counts are receipted into the trace.
        """
        moment = _parse_now(now)
        known = {rule.rule_id for rule in self.trigger_engine.rules()}
        for rule in derive_commitment_rules(self.ledger, moment, ahead_days=ahead_days):
            if rule.rule_id not in known:
                self.trigger_engine.add_rule(rule)
        fired = self.trigger_engine.tick(moment)
        self.trace.record_receipt(now, {"action": "triggers", "fired": len(fired)})
        return fired

    def export_bundle(self, directory: str | Path) -> dict[str, Any]:
        """Write the derived state into a self-describing bundle.

        The journal itself stays put (it is the source of truth); the
        bundle carries ``ledger.json``, ``snapshot.json``, and a
        ``manifest.json`` with counts, journal head, trace head, and the
        projection digest, so a receiver can audit the export without
        access to the database. Returns the manifest.
        """
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / "ledger.json").write_text(self.ledger.to_json() + "\n", encoding="utf-8")
        snap = self.snapshot()
        (target / "snapshot.json").write_text(
            json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest: dict[str, Any] = {
            "events": len(self.journal),
            "memories": sum(len(ids) for ids in snap["memories"].values()),
            "commitments": len(snap["commitments"]),
            "tombstones": len(snap["tombstones"]),
            "journal_head": snap["head"],
            "trace_head": self.trace.last_hash(),
            "projection_digest": snap["digest"],
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return manifest

    def remember(
        self,
        text: str,
        *,
        now: str,
        title: str = "",
        tags: list[str] | None = None,
        author: str = "user",
    ) -> str:
        """Record a note into the journal and project it.

        The event is content-addressed, so remembering the same text at
        the same instant is idempotent. ``now`` must be an explicit ISO
        instant — the workspace never reads the wall clock.
        """
        moment = _parse_now(now)
        content: dict[str, object] = {
            "text": text,
            "title": title,
            "author": author,
            "tags": sorted(tags or []),
        }
        event = Event(EventType.NOTE, moment, content)
        self.ingest_events([event], now=now)
        self.trace.record_decision(now, {"action": "remember", "event_id": event.event_id})
        return event.event_id

    def forget(self, item_id: str, *, now: str, reason: str = "") -> DeletionReport:
        """Forget an item: delete with cascade, then tombstone it.

        The journal frame stays (the hash chain must remain verifiable),
        but the tombstone blocks the event from ever being re-projected
        — on rebuild, on reopen, and on re-ingestion of the same event.
        Ledger commitments sourced from deleted events are dropped too.
        """
        moment = _parse_now(now)
        report = forget_item(
            self.deletion,
            item_id,
            DeletionReason.USER_REQUEST,
            moment,
            requested_by="user",
        )
        deleted_keys = {entry.key for entry in report.deleted} | {item_id}
        for commitment in self.ledger.all_commitments():
            if set(commitment.source_event_ids) & deleted_keys:
                self.ledger.remove(commitment.commitment_id)
        self.journal.record_tombstone(item_id, reason or "user request")
        self.trace.record_receipt(
            now,
            {"action": "forget", "item_id": item_id, "deleted": report.total_deleted},
        )
        return report

    # -- queries ---------------------------------------------------------------

    def ask(
        self,
        query: str,
        *,
        top_k: int = 5,
        as_of: str = "",
        now: str = "",
    ) -> list[SearchResult]:
        """Search the workspace with the structured query grammar.

        Supports the ``tag:`` / ``person:`` / ``project:`` / ``before:`` /
        ``after:`` / ``on:`` filters; ``as_of`` additionally hides any
        memory created after that instant. Citations in the results
        always resolve to live (non-forgotten) memories. The lookup is
        mirrored into the trace when ``now`` is given.
        """
        results = self.engine.search_parsed(parse_query(query), top_k=top_k, as_of=as_of)
        if now:
            self.trace.record_recall(now, {"query": query, "hits": [r.item_id for r in results]})
        return results

    def recall(self, item_id: str, *, now: str = "") -> MemoryItem | None:
        """Fetch one memory by id, honoring tombstones.

        Returns None for unknown ids AND for forgotten ids — tombstoned
        content must never resurface through direct recall either. A
        successful recall records access (feeding salience/decay) and is
        mirrored into the trace when ``now`` is given.
        """
        if self._is_tombstoned(item_id):
            return None
        item = self.store.get(item_id)
        if item is not None and now:
            self.trace.record_recall(now, {"item_id": item_id})
        return item


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Deterministic diff between two :meth:`Workspace.snapshot` dicts.

    Reports added/removed memory ids per tier, added/removed commitments
    with their status changes, and newly tombstoned events. ``empty`` is
    True exactly when the two projections are identical — the shape
    audits and migration tests rely on.
    """
    memory_diff: dict[str, dict[str, list[str]]] = {}
    tiers = sorted(set(before.get("memories", {})) | set(after.get("memories", {})))
    for tier in tiers:
        old = set(before.get("memories", {}).get(tier, []))
        new = set(after.get("memories", {}).get(tier, []))
        if old != new:
            memory_diff[tier] = {"added": sorted(new - old), "removed": sorted(old - new)}
    old_commits: dict[str, str] = before.get("commitments", {})
    new_commits: dict[str, str] = after.get("commitments", {})
    status_changes = [
        {"commitment_id": cid, "before": old_commits[cid], "after": new_commits[cid]}
        for cid in sorted(set(old_commits) & set(new_commits))
        if old_commits[cid] != new_commits[cid]
    ]
    diff: dict[str, Any] = {
        "memories": memory_diff,
        "commitments": {
            "added": sorted(set(new_commits) - set(old_commits)),
            "removed": sorted(set(old_commits) - set(new_commits)),
            "status_changes": status_changes,
        },
        "tombstones_added": sorted(
            set(after.get("tombstones", [])) - set(before.get("tombstones", []))
        ),
        "digest_changed": before.get("digest") != after.get("digest"),
    }
    diff["empty"] = (
        not memory_diff
        and not diff["commitments"]["added"]
        and not diff["commitments"]["removed"]
        and not status_changes
        and not diff["tombstones_added"]
        and not diff["digest_changed"]
    )
    return diff
