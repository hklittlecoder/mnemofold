"""Export bundle: manifest, ledger snapshot, and byte-level determinism."""

import json

from mnemofold.factory import WorkHistoryFactory
from mnemofold.ledger import CommitmentLedger
from mnemofold.workspace import Workspace

NOW = "2026-01-04T12:00:00+00:00"

MANIFEST_KEYS = {
    "events",
    "memories",
    "commitments",
    "tombstones",
    "journal_head",
    "trace_head",
    "projection_digest",
}


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=17, days=4)
    synthetic, _manifest = factory.generate()
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events([e.to_event() for e in synthetic], now=NOW)
    return ws


class TestExportBundle:
    def test_manifest_shape(self, tmp_path):
        ws = make_workspace(tmp_path)
        manifest = ws.export_bundle(tmp_path / "bundle")
        assert set(manifest) == MANIFEST_KEYS
        assert manifest["events"] > 0
        ws.close()

    def test_bundle_files_written(self, tmp_path):
        ws = make_workspace(tmp_path)
        out = tmp_path / "bundle"
        ws.export_bundle(out)
        for name in ("ledger.json", "snapshot.json", "manifest.json"):
            assert (out / name).exists(), name
        ws.close()

    def test_double_export_is_byte_identical(self, tmp_path):
        ws = make_workspace(tmp_path)
        a, b = tmp_path / "a", tmp_path / "b"
        m1 = ws.export_bundle(a)
        m2 = ws.export_bundle(b)
        assert m1 == m2
        for name in ("ledger.json", "snapshot.json", "manifest.json"):
            assert (a / name).read_bytes() == (b / name).read_bytes(), name
        ws.close()

    def test_manifest_file_matches_returned_dict(self, tmp_path):
        ws = make_workspace(tmp_path)
        out = tmp_path / "bundle"
        manifest = ws.export_bundle(out)
        on_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert on_disk == manifest
        ws.close()

    def test_ledger_snapshot_roundtrips(self, tmp_path):
        ws = make_workspace(tmp_path)
        out = tmp_path / "bundle"
        ws.export_bundle(out)
        loaded = CommitmentLedger.from_json((out / "ledger.json").read_text(encoding="utf-8"))
        assert loaded.total_count() == ws.ledger.total_count()
        ws.close()

    def test_snapshot_matches_live_snapshot(self, tmp_path):
        ws = make_workspace(tmp_path)
        out = tmp_path / "bundle"
        ws.export_bundle(out)
        on_disk = json.loads((out / "snapshot.json").read_text(encoding="utf-8"))
        assert on_disk == json.loads(json.dumps(ws.snapshot(), sort_keys=True))
        ws.close()

    def test_bundle_reflects_forget(self, tmp_path):
        ws = make_workspace(tmp_path)
        before = ws.export_bundle(tmp_path / "b1")
        from mnemofold.memory import MemoryTier

        target = None
        for tier in MemoryTier:
            items = ws.store.items_by_tier(tier)
            if items:
                target = items[0].item_id
                break
        assert target is not None
        ws.forget(target, now=NOW)
        after = ws.export_bundle(tmp_path / "b2")
        assert after["tombstones"] >= before["tombstones"] + 1
        ws.close()
