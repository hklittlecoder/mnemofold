"""The export command's bundle mode writes the full auditable package."""

import json

from mnemofold.cli import main
from mnemofold.ledger import CommitmentLedger
from mnemofold.workspace import Workspace


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "7"]) == 0


class TestExportBundleCli:
    def test_bundle_files_and_manifest(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        out_dir = tmp_path / "bundle"
        rc = main(["export", "--db", str(db), "--bundle", str(out_dir)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Wrote workspace bundle" in out
        for name in ("ledger.json", "snapshot.json", "manifest.json"):
            assert (out_dir / name).exists(), name
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["events"] > 0
        assert set(manifest) >= {
            "events",
            "memories",
            "commitments",
            "tombstones",
            "journal_head",
            "trace_head",
            "projection_digest",
        }

    def test_bundle_ledger_reads_back(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        out_dir = tmp_path / "bundle"
        main(["export", "--db", str(db), "--bundle", str(out_dir)])
        capsys.readouterr()
        loaded = CommitmentLedger.from_json((out_dir / "ledger.json").read_text(encoding="utf-8"))
        ws = Workspace(db)
        try:
            assert loaded.total_count() == ws.ledger.total_count()
        finally:
            ws.close()

    def test_bundle_snapshot_matches_live_snapshot(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        out_dir = tmp_path / "bundle"
        main(["export", "--db", str(db), "--bundle", str(out_dir)])
        capsys.readouterr()
        on_disk = json.loads((out_dir / "snapshot.json").read_text(encoding="utf-8"))
        ws = Workspace(db)
        try:
            assert on_disk == json.loads(json.dumps(ws.snapshot(), sort_keys=True))
        finally:
            ws.close()

    def test_plain_export_still_works(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["export", "--db", str(db)])
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out)["stats"]["events"] > 0
