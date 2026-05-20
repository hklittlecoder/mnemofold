"""Healthy-workspace integrity reports and the no-mutation contract."""

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


def first_item(ws: Workspace):
    for tier in MemoryTier:
        items = ws.store.items_by_tier(tier)
        if items:
            return items[0]
    raise AssertionError("workspace projected no memories")


class TestVerifyIntegrity:
    def test_healthy_workspace_passes_every_check(self, tmp_path):
        ws = make_workspace(tmp_path)
        report = ws.verify_integrity()
        assert report["ok"] is True
        assert all(report["checks"].values())
        assert report["frames_checked"] > 0
        assert report["tombstones"] == 0
        assert report["resurrected_keys"] == []
        assert len(report["projection_digest"]) == 64
        ws.close()

    def test_verify_does_not_mutate_state(self, tmp_path):
        ws = make_workspace(tmp_path)
        before = ws.projection_digest()
        stats_before = ws.stats()
        ws.verify_integrity()
        ws.verify_integrity()
        assert ws.projection_digest() == before
        assert ws.stats() == stats_before
        ws.close()

    def test_still_ok_after_a_clean_forget(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_item(ws).item_id
        ws.forget(target, now=NOW, reason="test")
        report = ws.verify_integrity()
        assert report["ok"] is True
        assert report["tombstones"] >= 1
        assert report["resurrected_keys"] == []
        ws.close()

    def test_report_shape_is_stable(self, tmp_path):
        ws = make_workspace(tmp_path)
        report = ws.verify_integrity()
        assert set(report) == {
            "ok",
            "checks",
            "frames_checked",
            "first_bad_frame",
            "tombstones",
            "resurrected_keys",
            "projection_digest",
            "journal",
        }
        assert report["journal"]["frames"] == report["frames_checked"]
        assert set(report["checks"]) == {
            "journal_chain",
            "trace_chain",
            "no_resurrection",
            "projection_stable",
        }
        ws.close()
