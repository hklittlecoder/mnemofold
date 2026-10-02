"""Session summary: aggregated, JSON-safe, and strictly read-only."""

import json

from mnemofold.factory import WorkHistoryFactory
from mnemofold.workspace import Workspace

NOW = "2026-01-04T12:00:00+00:00"


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=5, days=4)
    synthetic, _ = factory.generate()
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events([e.to_event() for e in synthetic], now=NOW)
    return ws


class TestSessionSummary:
    def test_shape_and_json_safety(self, tmp_path):
        ws = make_workspace(tmp_path)
        summary = ws.session_summary()
        assert set(summary) == {"stats", "integrity", "aging", "journal", "trace"}
        text = json.dumps(summary, sort_keys=True)  # must not raise
        assert json.loads(text) == summary
        ws.close()

    def test_consistent_with_parts(self, tmp_path):
        ws = make_workspace(tmp_path)
        summary = ws.session_summary()
        assert summary["stats"]["events"] == len(ws.journal)
        assert summary["journal"]["frames"] == len(ws.journal)
        assert summary["integrity"]["ok"] is True
        assert summary["aging"]["total_active"] == sum(summary["aging"]["counts"].values())
        assert summary["trace"]["entries"] > 0
        ws.close()

    def test_read_only_contract(self, tmp_path):
        ws = make_workspace(tmp_path)
        before = ws.projection_digest()
        ws.session_summary()
        ws.session_summary()
        assert ws.projection_digest() == before
        ws.close()

    def test_reflects_forget(self, tmp_path):
        ws = make_workspace(tmp_path)
        victim = None
        from mnemofold.memory import MemoryTier

        for tier in MemoryTier:
            items = ws.store.items_by_tier(tier)
            if items:
                victim = items[0].item_id
                break
        assert victim is not None
        ws.forget(victim, now=NOW)
        summary = ws.session_summary()
        assert summary["stats"]["tombstones"] >= 1
        assert summary["integrity"]["ok"] is True
        ws.close()
