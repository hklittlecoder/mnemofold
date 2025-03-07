import json

import pytest

from mnemofold import __version__
from mnemofold.cli import build_parser, main


def test_parser_has_version_subcommand():
    parser = build_parser()
    args = parser.parse_args(["version"])
    assert args.command == "version"


def test_cmd_version_prints_version(capsys):
    rc = main(["version"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == __version__


def test_parser_has_eval_subcommand():
    parser = build_parser()
    args = parser.parse_args(["eval", "--seed", "7", "--days", "10"])
    assert args.command == "eval"
    assert args.seed == 7
    assert args.days == 10


def test_cmd_eval_runs(capsys):
    rc = main(["eval", "--seed", "42", "--days", "7"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Events:" in out
    assert "planted commitments" in out.lower() or "planted_commitments" in out.lower()


def test_cmd_eval_json_output(capsys):
    main(["eval", "--seed", "1", "--days", "5", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["scenario"] == "eval-seed1-5d"
    assert "metrics" in data
    assert "event_count" in [m["name"] for m in data["metrics"]]


def test_cmd_demo_runs(capsys):
    rc = main(["demo", "--seed", "42", "--days", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "mnemofold demo" in out
    assert "Generated" in out
    assert "triage" in out.lower()
    assert "Standup" in out
    assert "Scorecard" in out


def test_cmd_replay_nonexistent_file(capsys):
    rc = main(["replay", "/tmp/nonexistent.jsonl"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


def test_cmd_replay_valid_trace(tmp_path, capsys):
    from mnemofold.replay import TraceRecorder

    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("2026-01-01T00:00:00Z", {"type": "test"})
        rec.record_decision("2026-01-01T00:01:00Z", {"ok": True})

    rc = main(["replay", str(p)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Entries: 2" in out
    assert "event: 1" in out
    assert "decision: 1" in out


def test_cmd_diff_identical_traces(tmp_path, capsys):
    from mnemofold.replay import TraceRecorder

    p1 = tmp_path / "a.jsonl"
    p2 = tmp_path / "b.jsonl"
    for p in (p1, p2):
        with TraceRecorder(p) as rec:
            rec.record_event("t1", {"x": 1})

    rc = main(["diff", str(p1), str(p2)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Equal: True" in out


def test_cmd_diff_different_traces(tmp_path, capsys):
    from mnemofold.replay import TraceRecorder

    p1 = tmp_path / "a.jsonl"
    p2 = tmp_path / "b.jsonl"
    with TraceRecorder(p1) as rec:
        rec.record_event("t1", {"x": 1})
    with TraceRecorder(p2) as rec:
        rec.record_event("t1", {"x": 2})

    rc = main(["diff", str(p1), str(p2)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "Equal: False" in out


def test_parser_has_replay_subcommand():
    parser = build_parser()
    args = parser.parse_args(["replay", "trace.jsonl"])
    assert args.command == "replay"
    assert args.trace == "trace.jsonl"


def test_parser_has_diff_subcommand():
    parser = build_parser()
    args = parser.parse_args(["diff", "a.jsonl", "b.jsonl"])
    assert args.command == "diff"
    assert args.trace_a == "a.jsonl"
    assert args.trace_b == "b.jsonl"


def test_unknown_command_errors():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nonexistent_command"])
