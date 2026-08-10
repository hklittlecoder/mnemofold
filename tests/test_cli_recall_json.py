"""The recall command's JSON mode mirrors the text fields exactly."""

import json

from mnemofold.cli import main

NOW = "2026-03-01T09:00:00+00:00"


def remembered(tmp_path):
    db = tmp_path / "ws"
    assert (
        main(
            [
                "remember",
                "--db",
                str(db),
                "--text",
                "release checklist details",
                "--title",
                "checklist",
                "--tags",
                "release,ops",
                "--now",
                NOW,
            ]
        )
        == 0
    )
    return db


class TestRecallJson:
    def test_json_fields(self, tmp_path, capsys):
        db = remembered(tmp_path)
        capsys.readouterr()
        # discover the id via ask
        main(["ask", "--db", str(db), "checklist", "--json"])
        hits = json.loads(capsys.readouterr().out)
        assert hits
        rc = main(["recall", "--db", str(db), hits[0]["item_id"], "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert set(payload) == {
            "item_id",
            "tier",
            "title",
            "created_at",
            "tags",
            "content",
        }
        # projection also tags items with their event type ("note")
        assert payload["tags"] == ["note", "ops", "release"]
        assert "release checklist details" in payload["content"]

    def test_text_mode_unchanged(self, tmp_path, capsys):
        db = remembered(tmp_path)
        capsys.readouterr()
        main(["ask", "--db", str(db), "checklist", "--json"])
        hits = json.loads(capsys.readouterr().out)
        rc = main(["recall", "--db", str(db), hits[0]["item_id"]])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.startswith("id: ")
        assert "tags: note, ops, release" in out

    def test_unknown_id_errors_in_both_modes(self, tmp_path, capsys):
        db = remembered(tmp_path)
        capsys.readouterr()
        assert main(["recall", "--db", str(db), "ghost", "--json"]) == 1
        assert "no live memory" in capsys.readouterr().err

    def test_forgotten_id_errors(self, tmp_path, capsys):
        db = remembered(tmp_path)
        capsys.readouterr()
        main(["ask", "--db", str(db), "checklist", "--json"])
        item_id = json.loads(capsys.readouterr().out)[0]["item_id"]
        assert main(["forget", "--db", str(db), item_id, "--now", NOW]) == 0
        capsys.readouterr()
        assert main(["recall", "--db", str(db), item_id, "--json"]) == 1
