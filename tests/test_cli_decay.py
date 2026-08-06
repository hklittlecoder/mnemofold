"""The decay subcommand reports exactly what the engine did."""

import json

from mnemofold.cli import main

OLD = "2026-01-01T09:00:00+00:00"
LATER = "2027-06-01T09:00:00+00:00"


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "7"]) == 0


class TestDecayCli:
    def test_json_counters(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["decay", "--db", str(db), "--now", LATER, "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        counters = json.loads(out)
        assert set(counters) == {"demoted", "tombstoned", "purged", "protected_skipped"}
        assert all(isinstance(v, int) for v in counters.values())

    def test_text_mode(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["decay", "--db", str(db), "--now", LATER])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Decay pass ===" in out

    def test_missing_workspace_errors(self, tmp_path, capsys):
        rc = main(["decay", "--db", str(tmp_path / "nope"), "--now", LATER])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err

    def test_decay_is_deterministic_on_fresh_copies(self, tmp_path, capsys):
        db_a, db_b = tmp_path / "a", tmp_path / "b"
        ingest(db_a)
        ingest(db_b)
        capsys.readouterr()
        main(["decay", "--db", str(db_a), "--now", LATER, "--json"])
        first = json.loads(capsys.readouterr().out)
        main(["decay", "--db", str(db_b), "--now", LATER, "--json"])
        assert json.loads(capsys.readouterr().out) == first
