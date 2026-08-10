"""Prep command output modes: parseable JSON, written HTML, stable text."""

import json

from mnemofold.cli import main


class TestPrepOutputs:
    def test_json_output_is_real_json(self, capsys):
        rc = main(["prep", "--seed", "5", "--days", "7", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)  # used to print a repr, which never parsed
        assert payload["meeting_id"] == "sync"
        assert "items" in payload and "agenda_items" in payload
        assert payload["total_items"] == len(payload["items"])

    def test_html_written_to_file(self, tmp_path, capsys):
        out_file = tmp_path / "prep.html"
        rc = main(["prep", "--seed", "5", "--days", "7", "--html", str(out_file)])
        assert rc == 0
        assert "Wrote meeting prep HTML" in capsys.readouterr().out
        text = out_file.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html>")
        assert "Meeting Prep" in text

    def test_html_is_deterministic(self, tmp_path, capsys):
        a, b = tmp_path / "a.html", tmp_path / "b.html"
        main(["prep", "--seed", "5", "--days", "7", "--html", str(a)])
        main(["prep", "--seed", "5", "--days", "7", "--html", str(b)])
        capsys.readouterr()
        assert a.read_bytes() == b.read_bytes()

    def test_text_mode_unchanged(self, capsys):
        rc = main(["prep", "--seed", "5", "--days", "7"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Meeting Prep: sync ===" in out

    def test_json_items_match_to_dict_shape(self, capsys):
        main(["prep", "--seed", "5", "--days", "7", "--json"])
        payload = json.loads(capsys.readouterr().out)
        for item in payload["items"]:
            assert set(item) == {
                "item_id",
                "title",
                "category",
                "summary",
                "citation",
                "priority",
            }
