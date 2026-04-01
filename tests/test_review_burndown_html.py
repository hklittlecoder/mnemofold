"""Weekly review HTML with the optional burndown chart."""

from mnemofold.cli import main
from mnemofold.review import WeeklyReview, render_weekly_html

SERIES = [
    {"day": "2026-03-01", "created": 1, "resolved": 0, "open": 1},
    {"day": "2026-03-02", "created": 3, "resolved": 1, "open": 2},
    {"day": "2026-03-03", "created": 3, "resolved": 3, "open": 0},
]


def make_review() -> WeeklyReview:
    return WeeklyReview(
        week_start="2026-03-01",
        week_end="2026-03-08",
        completed=["draft spec [c1]"],
        citations=["c1"],
    )


class TestReviewBurndownHtml:
    def test_without_series_no_chart(self):
        html_out = render_weekly_html(make_review())
        assert "Burndown" not in html_out
        assert "<polyline" not in html_out

    def test_with_series_embeds_chart(self):
        html_out = render_weekly_html(make_review(), SERIES)
        assert "Burndown" in html_out
        assert html_out.count("<polyline") == 2

    def test_rendering_is_deterministic(self):
        a = render_weekly_html(make_review(), SERIES)
        b = render_weekly_html(make_review(), SERIES)
        assert a == b

    def test_cli_html_includes_chart(self, tmp_path, capsys):
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
                "--html",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Burndown" in out
        assert "<svg" in out

    def test_cli_markdown_has_no_chart(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "7"])
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
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "<polyline" not in out

    def test_cli_bad_dates_error(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"])
        capsys.readouterr()
        rc = main(
            [
                "review",
                "--db",
                str(db),
                "--start",
                "garbage",
                "--end",
                "2025-01-08T00:00:00+00:00",
                "--html",
            ]
        )
        assert rc == 1
        assert "ISO dates" in capsys.readouterr().err

    def test_html_output_is_a_full_page(self, tmp_path, capsys):
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
                "--html",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert out.startswith("<!DOCTYPE html>")
