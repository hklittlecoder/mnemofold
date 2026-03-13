"""Workspace-level forget previews: accurate, non-mutating, ledger-aware."""

from mnemofold.factory import WorkHistoryFactory
from mnemofold.memory import MemoryTier
from mnemofold.workspace import Workspace

NOW = "2026-01-04T12:00:00+00:00"


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=5, days=3)
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


class TestForgetPreview:
    def test_preview_plans_the_cascade(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_memory(ws)
        preview = ws.forget_preview(target)
        assert preview["requested_key"] == target
        assert target in [entry["key"] for entry in preview["would_delete"]]
        assert isinstance(preview["ledger_commitments_affected"], list)
        ws.close()

    def test_preview_mutates_nothing(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_memory(ws)
        digest_before = ws.projection_digest()
        ws.forget_preview(target)
        ws.forget_preview(target)
        assert ws.projection_digest() == digest_before
        assert ws.recall(target) is not None
        assert ws.verify_integrity()["tombstones"] == 0
        ws.close()

    def test_preview_matches_executed_forget(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_memory(ws)
        preview = ws.forget_preview(target)
        report = ws.forget(target, now=NOW)
        executed = [entry.key for entry in report.deleted]
        planned = [entry["key"] for entry in preview["would_delete"]]
        assert executed == planned
        ws.close()

    def test_after_forget_preview_is_empty(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_memory(ws)
        ws.forget(target, now=NOW)
        preview = ws.forget_preview(target)
        assert preview["would_delete"] == []
        assert preview["total"] == 0
        ws.close()
