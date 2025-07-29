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

from mnemofold.deletion import DeletionEngine
from mnemofold.events import Event
from mnemofold.ingest import CommitmentExtractor
from mnemofold.ledger import Commitment, CommitmentLedger
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.replay import TraceRecorder
from mnemofold.retrieval import RetrievalEngine, build_deletion_engine
from mnemofold.storage import Journal


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
    """Deterministic projection of one event into an episodic memory."""
    parts = [str(v) for _k, v in sorted(event.content.items()) if isinstance(v, str) and v]
    text = " ".join(parts) or str(event.event_type.value)
    title = str(
        event.content.get("subject") or event.content.get("title") or event.event_type.value
    )
    return MemoryItem(
        item_id=event.event_id,
        tier=MemoryTier.EPISODIC,
        content=text,
        title=title,
        created_at=event.timestamp.isoformat(),
        tags={event.event_type.value},
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
