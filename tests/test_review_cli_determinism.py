"""Two identical review invocations must print identical bytes."""

from mnemofold.cli import main


def run_review(capsys, db, html: bool) -> str:
    argv = [
        "review",
        "--db",
        str(db),
        "--start",
        "2025-01-01T00:00:00+00:00",
        "--end",
        "2025-01-08T00:00:00+00:00",
    ]
    if html:
        argv.append("--html")
    assert main(argv) == 0
    return capsys.readouterr().out


class TestReviewCliDeterminism:
    def test_html_run_twice_identical(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert main(["ingest", "--db", str(db), "--seed", "21", "--days", "10"]) == 0
        capsys.readouterr()
        first = run_review(capsys, db, html=True)
        second = run_review(capsys, db, html=True)
        assert first == second
        assert "Burndown" in first

    def test_markdown_run_twice_identical(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert main(["ingest", "--db", str(db), "--seed", "21", "--days", "10"]) == 0
        capsys.readouterr()
        assert run_review(capsys, db, html=False) == run_review(capsys, db, html=False)

    def test_burndown_labels_window_ends(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert main(["ingest", "--db", str(db), "--seed", "21", "--days", "10"]) == 0
        capsys.readouterr()
        out = run_review(capsys, db, html=True)
        # the chart labels the first and last day of the 7-day window
        assert "2025-01-01" in out
        assert "2025-01-07" in out
