"""Sweeping previews across every memory: read-only until the real forget."""

from mnemofold.factory import WorkHistoryFactory
from mnemofold.memory import MemoryTier
from mnemofold.workspace import Workspace

NOW = "2026-01-04T12:00:00+00:00"


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=9, days=4)
    synthetic, _manifest = factory.generate()
    typed = [e.to_event() for e in synthetic]
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events(typed, now=NOW)
    return ws


def all_memory_ids(ws: Workspace) -> list[str]:
    ids: list[str] = []
    for tier in MemoryTier:
        ids.extend(i.item_id for i in ws.store.items_by_tier(tier))
    return sorted(ids)


class TestPreviewCycle:
    def test_sweeping_previews_keeps_digest_stable(self, tmp_path):
        ws = make_workspace(tmp_path)
        digest = ws.projection_digest()
        ids = all_memory_ids(ws)
        assert ids
        for item_id in ids:
            ws.forget_preview(item_id)
        assert ws.projection_digest() == digest
        assert ws.verify_integrity()["tombstones"] == 0
        ws.close()

    def test_forget_one_then_preview_rest(self, tmp_path):
        ws = make_workspace(tmp_path)
        ids = all_memory_ids(ws)
        victim = ids[0]
        ws.forget(victim, now=NOW)
        # previewing the deleted key is a no-op plan...
        assert ws.forget_preview(victim)["would_delete"] == []
        # ...and previews of the survivors no longer include the victim
        for item_id in ids[1:6]:
            preview = ws.forget_preview(item_id)
            assert victim not in [e["key"] for e in preview["would_delete"]]
        assert ws.verify_integrity()["ok"]
        ws.close()

    def test_integrity_holds_after_preview_and_forget_mix(self, tmp_path):
        ws = make_workspace(tmp_path)
        ids = all_memory_ids(ws)
        for item_id in ids[:3]:
            ws.forget_preview(item_id)
            ws.forget(item_id, now=NOW)
        report = ws.verify_integrity()
        assert report["ok"]
        assert report["tombstones"] >= 3
        assert report["resurrected_keys"] == []
        ws.close()
