"""The session subcommand: one-call operational handoff."""

import json

from mnemofold.cli import main
from mnemofold.workspace import Workspace

NOW = "2026-03-01T09:00:00+00:00"


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "5"]) == 0


class TestSessionCli:
    def test_text_summary(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["session", "--db", str(db)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Session summary ===" in out
        assert "integrity: PASS" in out
        assert "aging:" in out
        assert "trace:" in out

    def test_json_summary(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["session", "--db", str(db), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert set(payload) == {"stats", "integrity", "aging", "journal", "trace"}
        assert payload["integrity"]["ok"] is True
        assert payload["stats"]["events"] > 0

    def test_reflects_forget(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ws = Workspace(db)
        note_id = ws.remember("temporary note", now=NOW)
        ws.close()
        capsys.readouterr()
        assert main(["forget", "--db", str(db), note_id, "--now", NOW]) == 0
        capsys.readouterr()
        main(["session", "--db", str(db), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["stats"]["tombstones"] >= 1
        assert payload["integrity"]["ok"] is True

    def test_missing_workspace_errors(self, tmp_path, capsys):
        rc = main(["session", "--db", str(tmp_path / "nope")])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err

    def test_deterministic(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        main(["session", "--db", str(db), "--json"])
        first = capsys.readouterr().out
        main(["session", "--db", str(db), "--json"])
        assert capsys.readouterr().out == first
