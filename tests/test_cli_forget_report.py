"""The forget command's report formats."""

import json

from mnemofold.cli import main
from mnemofold.workspace import Workspace

NOW = "2026-01-05T09:00:00+00:00"


def prepared_db(tmp_path):
    db = tmp_path / "ws"
    ws = Workspace(db)
    note_id = ws.remember("release checklist details", title="note", now=NOW)
    ws.close()
    return db, note_id


class TestForgetReport:
    def test_json_report(self, tmp_path, capsys):
        db, note_id = prepared_db(tmp_path)
        rc = main(["forget", "--db", str(db), note_id, "--now", NOW, "--report", "json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["requested_key"] == note_id
        assert payload["reason"] == "user_request"
        assert payload["total_deleted"] >= 1

    def test_markdown_report(self, tmp_path, capsys):
        db, note_id = prepared_db(tmp_path)
        rc = main(["forget", "--db", str(db), note_id, "--now", NOW, "--report", "markdown"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.startswith("# Deletion Report")
        assert note_id in out

    def test_default_text_report_unchanged(self, tmp_path, capsys):
        db, note_id = prepared_db(tmp_path)
        rc = main(["forget", "--db", str(db), note_id, "--now", NOW])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.startswith("forgotten ")
        assert "tombstone recorded" in out

    def test_report_after_preview(self, tmp_path, capsys):
        db, note_id = prepared_db(tmp_path)
        main(["forget", "--db", str(db), note_id, "--now", NOW, "--preview"])
        preview_out = capsys.readouterr().out
        assert "nothing was deleted" in preview_out
        rc = main(["forget", "--db", str(db), note_id, "--now", NOW, "--report", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["total_deleted"] >= 1
