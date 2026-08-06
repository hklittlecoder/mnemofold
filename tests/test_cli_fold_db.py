"""Folding a real workspace from the CLI, in all three output modes."""

import json

from mnemofold.cli import main


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "10"]) == 0


class TestFoldCli:
    def test_db_mode_json(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["fold", "--db", str(db), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["items_before"] > 0
        assert payload["items_after"] <= payload["items_before"]

    def test_db_mode_text(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["fold", "--db", str(db)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Fold Report:" in out

    def test_html_output_written(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        out_file = tmp_path / "fold.html"
        rc = main(["fold", "--db", str(db), "--html", str(out_file)])
        assert rc == 0
        assert "Wrote fold report HTML" in capsys.readouterr().out
        text = out_file.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html>")
        assert "Fold report" in text

    def test_html_output_is_deterministic(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        a, b = tmp_path / "a.html", tmp_path / "b.html"
        main(["fold", "--db", str(db), "--html", str(a), "--now", "2026-01-01T02:00:00+00:00"])
        # second fold over the already-consolidated store: use a fresh copy
        db2 = tmp_path / "ws2"
        ingest(db2)
        main(["fold", "--db", str(db2), "--html", str(b), "--now", "2026-01-01T02:00:00+00:00"])
        assert a.read_bytes() == b.read_bytes()

    def test_missing_workspace_errors(self, tmp_path, capsys):
        rc = main(["fold", "--db", str(tmp_path / "nope")])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err

    def test_demo_mode_unchanged(self, capsys):
        rc = main(["fold", "--seed", "5", "--days", "10", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "fold_id" in json.loads(out)
