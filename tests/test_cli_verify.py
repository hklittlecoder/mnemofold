"""CLI surface for the integrity verification command."""

import json

from mnemofold.cli import main


def ingest_workspace(tmp_path, seed: int = 5, days: int = 3):
    db = tmp_path / "ws"
    rc = main(["ingest", "--db", str(db), "--seed", str(seed), "--days", str(days)])
    assert rc == 0
    return db


class TestCliVerify:
    def test_passes_on_healthy_workspace(self, tmp_path, capsys):
        db = ingest_workspace(tmp_path)
        capsys.readouterr()
        rc = main(["verify", "--db", str(db)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "mnemofold verify" in out
        assert "Result: PASS" in out
        assert "journal_chain: ok" in out

    def test_json_report_is_machine_readable(self, tmp_path, capsys):
        db = ingest_workspace(tmp_path)
        capsys.readouterr()
        rc = main(["verify", "--db", str(db), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        report = json.loads(out)
        assert report["ok"] is True
        assert report["frames_checked"] > 0
        assert report["checks"]["trace_chain"] is True

    def test_missing_workspace_errors(self, tmp_path, capsys):
        rc = main(["verify", "--db", str(tmp_path / "nope")])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err

    def test_verify_requires_db(self, capsys):
        import pytest

        with pytest.raises(SystemExit):
            main(["verify"])
