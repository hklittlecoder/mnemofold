"""The verify command's HTML report mode."""

from mnemofold.cli import main


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "4"]) == 0


class TestVerifyHtml:
    def test_html_written_on_pass(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        out_file = tmp_path / "integrity.html"
        rc = main(["verify", "--db", str(db), "--html", str(out_file)])
        assert rc == 0
        assert "Wrote integrity report HTML" in capsys.readouterr().out
        text = out_file.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html>")
        assert "<strong>PASS</strong>" in text
        assert "journal_chain" in text

    def test_html_is_deterministic(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        a, b = tmp_path / "a.html", tmp_path / "b.html"
        main(["verify", "--db", str(db), "--html", str(a)])
        main(["verify", "--db", str(db), "--html", str(b)])
        capsys.readouterr()
        assert a.read_bytes() == b.read_bytes()

    def test_json_mode_still_wins_over_text(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["verify", "--db", str(db), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.lstrip().startswith("{")

    def test_html_contains_journal_counters(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        out_file = tmp_path / "integrity.html"
        main(["verify", "--db", str(db), "--html", str(out_file)])
        text = out_file.read_text(encoding="utf-8")
        assert "frames_checked" in text
        assert "schema_version" in text
