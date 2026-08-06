"""The eval command's SVG output: real chart bytes, stable across runs."""

from pathlib import Path

from mnemofold.cli import main


class TestEvalSvg:
    def test_svg_file_written(self, tmp_path, capsys):
        out_file = tmp_path / "scorecard.svg"
        rc = main(["eval", "--seed", "3", "--days", "5", "--svg", str(out_file)])
        assert rc == 0
        assert out_file.exists()
        svg = out_file.read_text(encoding="utf-8")
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        err = capsys.readouterr().err
        assert "Wrote scorecard SVG" in err

    def test_svg_contains_aggregate_metrics(self, tmp_path, capsys):
        out_file = tmp_path / "scorecard.svg"
        main(["eval", "--seed", "3", "--days", "5", "--svg", str(out_file)])
        capsys.readouterr()
        svg = out_file.read_text(encoding="utf-8")
        assert "commitment_recall" in svg

    def test_svg_is_deterministic(self, tmp_path, capsys):
        a, b = tmp_path / "a.svg", tmp_path / "b.svg"
        main(["eval", "--seed", "3", "--days", "5", "--svg", str(a)])
        main(["eval", "--seed", "3", "--days", "5", "--svg", str(b)])
        capsys.readouterr()
        assert Path(a).read_bytes() == Path(b).read_bytes()

    def test_json_mode_still_clean_on_stdout(self, tmp_path, capsys):
        import json

        out_file = tmp_path / "scorecard.svg"
        rc = main(["eval", "--seed", "3", "--days", "5", "--json", "--svg", str(out_file)])
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)  # stdout stays pure JSON
        assert payload["overall_pass"] is True
        assert "Wrote scorecard SVG" in captured.err
