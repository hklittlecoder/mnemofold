"""After a real session, every audit surface tells the same story.

One workspace, one forget: the trace summary must show the receipts,
the deletion audit must count the tombstones by reason, and integrity
verification must pass over the whole combination.
"""

from mnemofold.factory import WorkHistoryFactory
from mnemofold.memory import MemoryTier
from mnemofold.replay import TraceReader
from mnemofold.workspace import Workspace

NOW = "2026-01-04T12:00:00+00:00"


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=13, days=4)
    synthetic, _manifest = factory.generate()
    typed = [e.to_event() for e in synthetic]
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events(typed, now=NOW)
    return ws


def first_memory(ws: Workspace) -> str:
    for tier in MemoryTier:
        items = ws.store.items_by_tier(tier)
        if items:
            return items[0].item_id
    raise AssertionError("no projected memories")


class TestAuditTrails:
    def test_trace_summary_reflects_session_receipts(self, tmp_path):
        ws = make_workspace(tmp_path)
        ws.forget(first_memory(ws), now=NOW)
        summary = TraceReader(ws.trace.path).summary()
        assert summary["by_kind"].get("receipt", 0) >= 2  # ingest + forget
        assert summary["entries"] >= 3
        ws.close()

    def test_deletion_audit_counts_reasons(self, tmp_path):
        ws = make_workspace(tmp_path)
        ws.forget(first_memory(ws), now=NOW)
        counts = ws.deletion.audit_report()
        assert counts.get("user_request", 0) >= 1
        ws.close()

    def test_integrity_passes_over_combined_session(self, tmp_path):
        ws = make_workspace(tmp_path)
        ws.ask("release", now=NOW)
        ws.forget(first_memory(ws), now=NOW)
        report = ws.verify_integrity()
        assert report["ok"] is True
        assert report["tombstones"] >= 1
        ws.close()

    def test_reopened_session_keeps_audit_state(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_memory(ws)
        ws.forget(target, now=NOW)
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)
        assert reopened.recall(target) is None
        summary = TraceReader(reopened.trace.path).summary()
        assert summary["by_kind"].get("receipt", 0) >= 2
        assert reopened.verify_integrity()["ok"]
        reopened.close()
