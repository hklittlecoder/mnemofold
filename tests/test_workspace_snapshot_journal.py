"""Snapshot journal counters survive rebuilds and reopens."""

from mnemofold.factory import WorkHistoryFactory
from mnemofold.workspace import Workspace

NOW = "2026-01-04T12:00:00+00:00"


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=5, days=3)
    synthetic, _manifest = factory.generate()
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events([e.to_event() for e in synthetic], now=NOW)
    return ws


class TestSnapshotJournal:
    def test_journal_stats_present_and_exact(self, tmp_path):
        ws = make_workspace(tmp_path)
        snap = ws.snapshot()
        assert snap["journal"]["frames"] == len(ws.journal)
        assert snap["journal"]["tombstones"] == 0
        assert snap["journal"]["head_checksum"] == snap["head"]
        ws.close()

    def test_tombstone_count_grows_with_forget(self, tmp_path):
        from mnemofold.memory import MemoryTier

        ws = make_workspace(tmp_path)
        target = None
        for tier in MemoryTier:
            items = ws.store.items_by_tier(tier)
            if items:
                target = items[0].item_id
                break
        assert target is not None
        ws.forget(target, now=NOW)
        assert ws.snapshot()["journal"]["tombstones"] == 1
        ws.close()

    def test_snapshot_is_deterministic(self, tmp_path):
        ws = make_workspace(tmp_path)
        assert ws.snapshot() == ws.snapshot()
        ws.close()

    def test_rebuild_preserves_journal_counters(self, tmp_path):
        ws = make_workspace(tmp_path)
        before = ws.snapshot()
        ws.rebuild()
        after = ws.snapshot()
        assert before["journal"] == after["journal"]
        assert before["digest"] == after["digest"]
        ws.close()

    def test_reopen_preserves_snapshot(self, tmp_path):
        ws = make_workspace(tmp_path)
        before = ws.snapshot()
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)
        assert reopened.snapshot() == before
        reopened.close()
