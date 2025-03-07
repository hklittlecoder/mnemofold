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


def test_parser_has_ledger_subcommand():
    parser = build_parser()
    args = parser.parse_args(["ledger", "--seed", "1", "--days", "5"])
    assert args.command == "ledger"
    assert args.seed == 1


def test_cmd_ledger_runs(capsys):
    rc = main(["ledger", "--seed", "42", "--days", "10"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Commitment Ledger" in out or "commitment" in out.lower()
    assert "Total" in out


def test_cmd_ledger_json(capsys):
    main(["ledger", "--seed", "1", "--days", "5", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "commitments" in data
    assert len(data["commitments"]) >= 1


def test_cmd_ledger_status_filter(capsys):
    rc = main(["ledger", "--seed", "7", "--days", "10", "--status", "open"])
    assert rc == 0
    # Should not crash with status filter


def test_parser_has_triage_subcommand():
    parser = build_parser()
    args = parser.parse_args(["triage", "--seed", "5", "--top", "3"])
    assert args.command == "triage"
    assert args.top == 3


def test_cmd_triage_runs(capsys):
    rc = main(["triage", "--seed", "42", "--days", "7", "--top", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Inbox Triage" in out
    assert "Scored" in out


def test_parser_has_fold_subcommand():
    parser = build_parser()
    args = parser.parse_args(["fold", "--seed", "3", "--days", "10"])
    assert args.command == "fold"
    assert args.days == 10


def test_cmd_fold_runs(capsys):
    rc = main(["fold", "--seed", "42", "--days", "7"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Fold Report" in out
    assert "Items before" in out
    assert "Items after" in out


def test_cmd_fold_json(capsys):
    main(["fold", "--seed", "1", "--days", "5", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "items_before" in data
    assert "items_after" in data
    assert "merges" in data


def test_parser_has_asof_subcommand():
    parser = build_parser()
    args = parser.parse_args(["asof", "--seed", "1", "--days", "5"])
    assert args.command == "asof"


def test_cmd_asof_runs(capsys):
    rc = main(["asof", "--seed", "42", "--days", "7"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "As-of query" in out
    assert "Valid on this date" in out


def test_cmd_asof_with_date(capsys):
    rc = main(["asof", "--seed", "42", "--days", "10", "--date", "2025-01-05"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2025-01-05" in out


def test_parser_has_context_subcommand():
    parser = build_parser()
    args = parser.parse_args(["context", "--budget", "1000"])
    assert args.command == "context"
    assert args.budget == 1000


def test_cmd_context_runs(capsys):
    rc = main(["context", "--seed", "42", "--days", "3", "--budget", "500"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Context Pack" in out
    assert "Items packed" in out
    assert "Tokens used" in out


def test_cmd_context_within_budget(capsys):
    main(["context", "--seed", "42", "--days", "3", "--budget", "100"])
    out = capsys.readouterr().out
    assert "Within budget" in out


def test_parser_has_prep_subcommand():
    parser = build_parser()
    args = parser.parse_args(["prep", "--meeting", "alpha-sync"])
    assert args.command == "prep"
    assert args.meeting == "alpha-sync"


def test_cmd_prep_runs(capsys):
    rc = main(["prep", "--seed", "42", "--days", "7", "--meeting", "sync"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Meeting Prep" in out
    assert "Attendees" in out
    assert "Agenda" in out


def test_parser_has_privacy_subcommand():
    parser = build_parser()
    args = parser.parse_args(["privacy", "--demo"])
    assert args.command == "privacy"
    assert args.demo is True


def test_cmd_privacy_demo(capsys):
    rc = main(["privacy", "--demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Privacy Scan" in out
    assert "PII matches" in out
    assert "email" in out.lower()
    assert "Redacted" in out


def test_cmd_privacy_hash_mode(capsys):
    rc = main(["privacy", "--demo", "--mode", "hash", "--salt", "test123"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pii:" in out or "email" in out.lower()


def test_parser_has_triggers_subcommand():
    parser = build_parser()
    args = parser.parse_args(["triggers", "--seed", "1"])
    assert args.command == "triggers"


def test_cmd_triggers_runs(capsys):
    rc = main(["triggers", "--seed", "42", "--days", "7"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Proactive Triggers" in out
    assert "Total fired" in out
    assert "Active" in out
