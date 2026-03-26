"""StandupData serialization and the CLI --json surface."""

from mnemofold.cli import main
from mnemofold.review import StandupData


class TestStandupToDict:
    def test_shape_and_defaults(self):
        data = StandupData(date="2026-03-10")
        d = data.to_dict()
        assert set(d) == {
            "date",
            "completed",
            "in_progress",
            "planned",
            "blockers",
            "open_commitments",
            "overdue",
            "pending_decisions",
            "citations",
        }
        assert d["date"] == "2026-03-10"
        assert all(d[key] == [] for key in d if key != "date")

    def test_lists_are_copied(self):
        data = StandupData(date="2026-03-10", completed=["c1"])
        d = data.to_dict()
        d["completed"].append("injected")
        assert data.to_dict()["completed"] == ["c1"]


class TestStandupCliJson:
    def test_json_output_parses_with_expected_keys(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"]) == 0
        capsys.readouterr()
        rc = main(["standup", "--db", str(db), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        import json

        payload = json.loads(out)
        assert "date" in payload
        assert "open_commitments" in payload

    def test_json_takes_precedence_over_html(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"])
        capsys.readouterr()
        rc = main(["standup", "--db", str(db), "--json", "--html"])
        out = capsys.readouterr().out
        assert rc == 0
        assert not out.lstrip().startswith("<")

    def test_markdown_remains_default(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"])
        capsys.readouterr()
        rc = main(["standup", "--db", str(db)])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() and not out.lstrip().startswith(("{", "<"))
