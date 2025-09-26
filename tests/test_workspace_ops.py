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


class TestWorkspaceDecay:
    def test_decay_receipts_counters_and_protects_holds(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(2))
            items = sorted(ws.store.items_by_tier(MemoryTier.EPISODIC), key=lambda i: i.item_id)
            ws.decay_engine.place_hold(items[0].item_id, reason="audit")
            stats = ws.apply_decay("2025-06-01T00:00:00+00:00")
            assert stats["protected_skipped"] >= 1
            assert ws.store.peek(items[0].item_id) is not None
            demoted = ws.store.peek(items[1].item_id)
            assert demoted is not None
            assert demoted.tier != MemoryTier.EPISODIC
            receipts = _receipts(tmp_path / "ws", "decay")
            assert len(receipts) == 1
            assert receipts[0]["protected_skipped"] == stats["protected_skipped"]
