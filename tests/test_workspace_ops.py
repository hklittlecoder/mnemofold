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


class TestWorkspaceTriage:
    def _items(self) -> list:
        from mnemofold.triage import TriageItem

        return [
            TriageItem(
                item_id=f"inbox-{i}",
                title=f"message {i}",
                sender="ana@team.example",
                received_at="2025-01-02T08:00:00+00:00",
                content="release blocking risk" if i == 0 else "newsletter digest",
                has_deadline=i == 0,
                deadline="2025-01-02T17:00:00+00:00" if i == 0 else "",
                has_explicit_ask=i == 0,
            )
            for i in range(3)
        ]

    def test_triage_conserves_items_and_receipts_totals(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            results, plan = ws.triage(self._items(), "2025-01-02T09:00:00+00:00")
            assert len(results) == 3
            assert plan.total() == 3
            assert _receipts(tmp_path / "ws", "triage") == [
                {
                    "action": "triage",
                    "scored": 3,
                    "act_now": len(plan.act_now),
                    "review": len(plan.review),
                    "defer": len(plan.defer),
                }
            ]

    def test_triage_is_deterministic_for_same_now(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            first, _ = ws.triage(self._items(), "2025-01-02T09:00:00+00:00")
            second, _ = ws.triage(self._items(), "2025-01-02T09:00:00+00:00")
            assert [r.score for r in first] == [r.score for r in second]
            assert [r.item_id for r in first] == [r.item_id for r in second]


class TestWorkspaceContextPack:
    def test_pack_stays_within_budget_and_cites_live_memories(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(4))
            pack = ws.context_pack(
                "release planning",
                budget_tokens=40,
                now="2025-01-02T09:00:00+00:00",
            )
            assert pack.total_tokens <= 40
            for item in pack.items:
                assert ws.store.peek(item.item_id) is not None
            receipts = _receipts(tmp_path / "ws", "context")
            assert len(receipts) == 1
            assert receipts[0]["tokens"] == pack.total_tokens

    def test_forgotten_memories_never_enter_the_pack(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(3))
            victim = sorted(ws.store.items_by_tier(MemoryTier.EPISODIC), key=lambda i: i.item_id)[0]
            ws.forget(victim.item_id, now="2025-01-02T00:00:00+00:00", reason="test")
            pack = ws.context_pack("release planning", budget_tokens=500)
            assert victim.item_id not in {item.item_id for item in pack.items}


class TestWorkspacePrep:
    def test_packet_cites_live_memories(self, tmp_path: Path):
        from mnemofold.prep import verify_citations

        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(3))
            packet = ws.prep(
                "mtg-1",
                "Release planning",
                ["Ana", "Bo"],
                context_text="release planning risks",
                now="2025-01-02T09:00:00+00:00",
            )
            assert packet.items
            assert verify_citations(packet, ws.store)
            receipts = _receipts(tmp_path / "ws", "prep")
            assert receipts[0]["items"] == packet.total_items


class TestWorkspaceStandup:
    def test_standup_lists_open_commitments_with_citations(self, tmp_path: Path):
        from mnemofold.ledger import Commitment

        with Workspace(tmp_path / "ws") as ws:
            ws.ledger.add(
                Commitment(
                    commitment_id="c-standup",
                    owed_by="ana",
                    owed_to="team",
                    description="ship the report",
                    due_date="2025-01-10T17:00:00+00:00",
                    created_at="2025-01-01T09:00:00+00:00",
                )
            )
            data = ws.standup("2025-01-02T08:00:00+00:00", now="2025-01-02T08:00:00+00:00")
            assert any("c-standup" in line for line in data.open_commitments)
            assert any("c-standup" in cite for cite in data.citations)
            receipts = _receipts(tmp_path / "ws", "standup")
            assert receipts[0]["open"] == len(data.open_commitments)
            assert receipts[0]["overdue"] == len(data.overdue)
