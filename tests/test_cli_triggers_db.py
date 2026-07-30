"""The triggers command in workspace mode."""

import json

from mnemofold.cli import main


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "14"]) == 0


class TestTriggersDbMode:
    def test_json_mode_parses(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["triggers", "--db", str(db), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert isinstance(payload, list)
        for entry in payload:
            assert set(entry) >= {"rule_id", "kind", "target_id", "severity", "message"}

    def test_text_mode_header(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["triggers", "--db", str(db)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Proactive Triggers ===" in out
        assert "Total fired:" in out

    def test_explicit_now_is_honored(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["triggers", "--db", str(db), "--now", "2030-01-01T00:00:00+00:00", "--json"])
        assert rc == 0
        json.loads(capsys.readouterr().out)

    def test_missing_workspace_errors(self, tmp_path, capsys):
        rc = main(["triggers", "--db", str(tmp_path / "nope")])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err

    def test_factory_mode_unchanged(self, capsys):
        rc = main(["triggers", "--seed", "5", "--days", "14"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Proactive Triggers ===" in out
