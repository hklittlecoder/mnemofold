"""Trace diff JSON output: machine-readable equality verdicts."""

import json

from mnemofold.cli import main
from mnemofold.replay import TraceRecorder


def write_trace(path, payloads):
    with TraceRecorder(path) as rec:
        for i, payload in enumerate(payloads):
            rec.record_event(f"2026-03-01T09:{i:02d}:00+00:00", payload)


class TestDiffJson:
    def test_identical_traces(self, tmp_path, capsys):
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        write_trace(a, [{"x": 1}, {"y": 2}])
        write_trace(b, [{"x": 1}, {"y": 2}])
        rc = main(["diff", str(a), str(b), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["equal"] is True
        assert payload["a_count"] == payload["b_count"] == 2
        assert payload["matching"] == 2
        assert payload["first_mismatch"] is None

    def test_divergent_traces(self, tmp_path, capsys):
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        write_trace(a, [{"x": 1}, {"y": 2}])
        write_trace(b, [{"x": 1}, {"y": 999}])
        rc = main(["diff", str(a), str(b), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert payload["equal"] is False
        assert payload["first_mismatch"] == 1

    def test_text_mode_unchanged(self, tmp_path, capsys):
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        write_trace(a, [{"x": 1}])
        write_trace(b, [{"x": 1}])
        rc = main(["diff", str(a), str(b)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Matching:" in out
