"""Tests for workspace-level operations layered on the journal.

Each operation mutates only derived projections (never the journal's
raw events), receipts its outcome into the replay trace, and must be
safe to re-run after a rebuild.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mnemofold.events import Event, EventType
from mnemofold.memory import MemoryTier
from mnemofold.replay import TraceReader
from mnemofold.workspace import Workspace


def _notes(count: int) -> list[Event]:
    return [
        Event(
            EventType.NOTE,
            datetime(2025, 1, 1, 9, i, tzinfo=UTC),
            {"text": f"release planning note {i}", "title": f"n{i}"},
        )
        for i in range(count)
    ]


def _receipts(ws_path: Path, action: str) -> list[dict]:
    return [
        entry.payload
        for entry in TraceReader(ws_path / "trace.jsonl").entries()
        if entry.payload.get("action") == action
    ]


class TestWorkspaceFold:
    def test_fold_promotes_salient_memories_and_receipts(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(2))
            for item in ws.store.items_by_tier(MemoryTier.EPISODIC):
                item.salience = 0.9
            report = ws.fold("2025-01-02T02:00:00+00:00")
            assert len(report.new_semantic) == 2
            assert _receipts(tmp_path / "ws", "fold") == [
                {"action": "fold", "fold_id": report.fold_id, "digest": report.digest()}
            ]

    def test_refold_after_rebuild_reproduces_the_digest(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(2))
            for item in ws.store.items_by_tier(MemoryTier.EPISODIC):
                item.salience = 0.9
            first = ws.fold("2025-01-02T02:00:00+00:00")
            ws.rebuild()  # folding is derived: promotions do not survive
            assert ws.store.items_by_tier(MemoryTier.SEMANTIC) == []
            for item in ws.store.items_by_tier(MemoryTier.EPISODIC):
                item.salience = 0.9
            second = ws.fold("2025-01-02T02:00:00+00:00")
            assert second.digest() == first.digest()
