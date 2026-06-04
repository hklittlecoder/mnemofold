"""Weekly review serialization and the CLI --json surface."""

import json

from mnemofold.cli import main
from mnemofold.review import WeeklyReview


class TestWeeklyReviewToDict:
    def test_shape(self):
        review = WeeklyReview(
            week_start="2026-03-02",
            week_end="2026-03-09",
            completed=["draft spec [c1]"],
            overdue=["late item [c2]"],
            stats={"completed_count": 1, "overdue_count": 1},
            citations=["c1", "c2"],
        )
        d = review.to_dict()
        assert set(d) == {
            "week_start",
            "week_end",
            "completed",
            "overdue",
            "still_open",
            "due_next_week",
            "risks",
            "citations",
            "stats",
        }
        assert d["completed"] == ["draft spec [c1]"]
        assert d["stats"] == {"completed_count": 1, "overdue_count": 1}

    def test_lists_are_copied(self):
        review = WeeklyReview(week_start="a", week_end="b", completed=["x"])
        d = review.to_dict()
        d["completed"].append("injected")
        assert review.to_dict()["completed"] == ["x"]


class TestReviewCliJson:
    def test_json_output_parses(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "7"]) == 0
        capsys.readouterr()
        rc = main(
            [
                "review",
                "--db",
                str(db),
                "--start",
                "2025-01-01T00:00:00+00:00",
                "--end",
                "2025-01-08T00:00:00+00:00",
                "--json",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["week_start"] == "2025-01-01T00:00:00+00:00"
        assert "stats" in payload

    def test_json_takes_precedence_over_html(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"])
        capsys.readouterr()
        rc = main(
            [
                "review",
                "--db",
                str(db),
                "--start",
                "2025-01-01T00:00:00+00:00",
                "--end",
                "2025-01-08T00:00:00+00:00",
                "--json",
                "--html",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert out.lstrip().startswith("{")

    def test_json_output_is_deterministic(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "7"])
        capsys.readouterr()
        argv = [
            "review",
            "--db",
            str(db),
            "--start",
            "2025-01-01T00:00:00+00:00",
            "--end",
            "2025-01-08T00:00:00+00:00",
            "--json",
        ]
        main(argv)
        first = capsys.readouterr().out
        main(argv)
        assert capsys.readouterr().out == first
