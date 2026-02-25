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


def test_cmd_eval_runs_scenario_suite(capsys):
    rc = main(["eval", "--seed", "42", "--days", "30"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "commitments-seed42-30d" in out
    assert "commitment_recall" in out
    assert "Aggregate pass: True" in out


def test_cmd_eval_json_has_cards_and_aggregate(capsys):
    main(["eval", "--seed", "1", "--days", "20", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["scenario"] == "eval-seed1-20d"
    assert len(data["cards"]) == 4
    assert data["aggregate"]["scenario"] == "aggregate"
    assert data["overall_pass"] is True
    card_scenarios = [card["scenario"] for card in data["cards"]]
    assert any(s.startswith("triage-") for s in card_scenarios)
    assert any(s.startswith("asof-") for s in card_scenarios)


class TestCmdIngest:
    def test_ingest_synthetic_creates_workspace(self, tmp_path, capsys):
        db = str(tmp_path / "ws")
        rc = main(["ingest", "--db", db, "--seed", "5", "--days", "10"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Ingested:" in out
        assert (tmp_path / "ws" / "journal.db").exists()

    def test_ingest_twice_is_idempotent(self, tmp_path, capsys):
        db = str(tmp_path / "ws")
        main(["ingest", "--db", db, "--seed", "5", "--days", "10"])
        capsys.readouterr()
        rc = main(["ingest", "--db", db, "--seed", "5", "--days", "10"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Ingested: 0 new events" in out

    def test_ingest_from_jsonl(self, tmp_path, capsys):
        from mnemofold.factory import WorkHistoryFactory

        factory = WorkHistoryFactory(seed=3, days=5)
        synthetic, _ = factory.generate()
        jsonl = tmp_path / "in.jsonl"
        jsonl.write_text(
            "\n".join(e.to_event().to_json() for e in synthetic[:10]) + "\n",
            encoding="utf-8",
        )
        db = str(tmp_path / "ws")
        rc = main(["ingest", "--db", db, "--jsonl", str(jsonl)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Ingested: 10 new events" in out

    def test_ingest_missing_jsonl_returns_1(self, tmp_path, capsys):
        rc = main(["ingest", "--db", str(tmp_path / "ws"), "--jsonl", "/no/such.jsonl"])
        assert rc == 1
        assert "not found" in capsys.readouterr().err


class TestCmdExport:
    def _ingested(self, tmp_path) -> str:
        db = str(tmp_path / "ws")
        main(["ingest", "--db", db, "--seed", "5", "--days", "14"])
        return db

    def test_export_json(self, tmp_path, capsys):
        db = self._ingested(tmp_path)
        capsys.readouterr()
        rc = main(["export", "--db", db, "--format", "json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["stats"]["events"] > 0
        assert "ledger" in data

    def test_export_markdown(self, tmp_path, capsys):
        db = self._ingested(tmp_path)
        capsys.readouterr()
        rc = main(["export", "--db", db, "--format", "markdown"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Commitment Ledger" in out

    def test_export_to_file(self, tmp_path, capsys):
        db = self._ingested(tmp_path)
        capsys.readouterr()
        out_file = tmp_path / "export.json"
        rc = main(["export", "--db", db, "--out", str(out_file)])
        assert rc == 0
        assert out_file.exists()
        assert json.loads(out_file.read_text())["stats"]["events"] > 0

    def test_export_missing_workspace_returns_1(self, tmp_path, capsys):
        rc = main(["export", "--db", str(tmp_path / "nope")])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err


class TestCmdMemoryOps:
    NOW = "2025-03-10T09:00:00+00:00"
    LATER = "2025-03-11T09:00:00+00:00"

    def _remember(self, tmp_path, capsys, text="buy milk"):
        db = str(tmp_path / "ws")
        rc = main(
            [
                "remember",
                "--db",
                db,
                "--text",
                text,
                "--title",
                "errand",
                "--tags",
                "home,shop",
                "--now",
                self.NOW,
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert out.startswith("remembered evt_")
        return db, out.strip().split()[1]

    def test_remember_recall_forget_flow(self, tmp_path, capsys):
        db, item_id = self._remember(tmp_path, capsys)
        rc = main(["recall", "--db", db, item_id])
        out = capsys.readouterr().out
        assert rc == 0
        assert "buy milk" in out
        assert "errand" in out
        assert "home" in out

        rc = main(["forget", "--db", db, item_id, "--now", self.LATER, "--reason", "done"])
        assert rc == 0
        assert "forgotten" in capsys.readouterr().out

        rc = main(["recall", "--db", db, item_id])
        assert rc == 1
        assert "no live memory" in capsys.readouterr().err

    def test_recall_unknown_item(self, tmp_path, capsys):
        db, _ = self._remember(tmp_path, capsys)
        rc = main(["recall", "--db", db, "evt_nope"])
        assert rc == 1
        assert "no live memory" in capsys.readouterr().err

    def test_remember_bad_now_exits_one(self, tmp_path, capsys):
        rc = main(["remember", "--db", str(tmp_path / "ws"), "--text", "x", "--now", "garbage"])
        assert rc == 1
        assert "invalid timestamp" in capsys.readouterr().err

    def test_forget_unknown_item_exits_one(self, tmp_path, capsys):
        db, _ = self._remember(tmp_path, capsys)
        rc = main(["forget", "--db", db, "evt_ghost", "--now", self.LATER])
        assert rc == 1

    def test_forget_missing_workspace(self, tmp_path, capsys):
        rc = main(["forget", "--db", str(tmp_path / "nope"), "evt_x", "--now", self.LATER])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err

    def test_remember_is_idempotent_from_cli(self, tmp_path, capsys):
        db, first = self._remember(tmp_path, capsys)
        rc = main(
            [
                "remember",
                "--db",
                db,
                "--text",
                "buy milk",
                "--title",
                "errand",
                "--tags",
                "home,shop",
                "--now",
                self.NOW,
            ]
        )
        second = capsys.readouterr().out.strip().split()[1]
        assert rc == 0
        assert first == second


class TestCmdAsk:
    def _seeded(self, tmp_path) -> str:
        db = str(tmp_path / "ws")
        main(["ingest", "--db", db, "--seed", "5", "--days", "20"])
        return db

    def test_ask_returns_results(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["ask", "--db", db, "milestone update"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "result(s) for: milestone update" in out

    def test_ask_json_shape(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["ask", "--db", db, "milestone", "--json", "--top", "3"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert isinstance(data, list)
        assert len(data) <= 3
        assert all("citation" in row for row in data)

    def test_ask_finds_remembered_note(self, tmp_path, capsys):
        db = str(tmp_path / "ws")
        main(
            [
                "remember",
                "--db",
                db,
                "--text",
                "zephyr launch checklist",
                "--now",
                "2025-03-01T09:00:00+00:00",
            ]
        )
        capsys.readouterr()
        rc = main(["ask", "--db", db, "zephyr", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data) >= 1  # the remembered note is findable by its text

    def test_ask_as_of_excludes_later(self, tmp_path, capsys):
        db = str(tmp_path / "ws")
        main(
            ["remember", "--db", db, "--text", "early zephyr", "--now", "2025-03-01T09:00:00+00:00"]
        )
        main(
            ["remember", "--db", db, "--text", "late zephyr", "--now", "2025-06-01T09:00:00+00:00"]
        )
        capsys.readouterr()
        rc = main(["ask", "--db", db, "zephyr", "--json", "--as-of", "2025-04-01T00:00:00+00:00"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data) == 1

    def test_ask_missing_workspace(self, tmp_path, capsys):
        rc = main(["ask", "--db", str(tmp_path / "nope"), "x"])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err


class TestCmdReports:
    def _seeded(self, tmp_path) -> str:
        db = str(tmp_path / "ws")
        main(["ingest", "--db", db, "--seed", "42", "--days", "30"])
        return db

    def test_standup_markdown(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["standup", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Standup" in out

    def test_standup_explicit_today_html(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["standup", "--db", db, "--today", "2025-01-20T00:00:00+00:00", "--html"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "<html" in out

    def test_standup_invalid_today_returns_1(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["standup", "--db", db, "--today", "garbage"])
        assert rc == 1
        assert "invalid standup date" in capsys.readouterr().err

    def test_review_markdown(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(
            [
                "review",
                "--db",
                db,
                "--start",
                "2025-01-06T00:00:00+00:00",
                "--end",
                "2025-01-13T00:00:00+00:00",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Weekly Review" in out

    def test_review_html(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(
            [
                "review",
                "--db",
                db,
                "--start",
                "2025-01-06T00:00:00+00:00",
                "--end",
                "2025-01-13T00:00:00+00:00",
                "--html",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "<html" in out

    def test_reports_missing_workspace(self, tmp_path, capsys):
        assert main(["standup", "--db", str(tmp_path / "nope")]) == 1
        capsys.readouterr()
        assert (
            main(
                [
                    "review",
                    "--db",
                    str(tmp_path / "nope"),
                    "--start",
                    "2025-01-06T00:00:00+00:00",
                    "--end",
                    "2025-01-13T00:00:00+00:00",
                ]
            )
            == 1
        )


class TestCmdPlaybooks:
    def _seeded(self, tmp_path, days=40) -> str:
        db = str(tmp_path / "ws")
        main(["ingest", "--db", db, "--seed", "5", "--days", str(days)])
        return db

    def test_playbooks_runs(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["playbooks", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "playbook proposal" in out

    def test_playbooks_json_is_list(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        rc = main(["playbooks", "--db", db, "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert isinstance(data, list)

    def test_high_min_repeats_yields_fewer(self, tmp_path, capsys):
        db = self._seeded(tmp_path)
        capsys.readouterr()
        main(["playbooks", "--db", db, "--min-repeats", "100000", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data == []

    def test_playbooks_missing_workspace(self, tmp_path, capsys):
        rc = main(["playbooks", "--db", str(tmp_path / "nope")])
        assert rc == 1
        assert "workspace not found" in capsys.readouterr().err


EXPECTED_SUBCOMMANDS = {
    "version",
    "eval",
    "demo",
    "replay",
    "diff",
    "ledger",
    "triage",
    "fold",
    "asof",
    "context",
    "prep",
    "privacy",
    "triggers",
    "ingest",
    "export",
    "remember",
    "forget",
    "recall",
    "ask",
    "standup",
    "review",
    "playbooks",
    "verify",
}


def _subparser_choices() -> dict:
    import argparse

    parser = build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices


class TestCliSurface:
    def test_all_subcommands_registered(self):
        assert set(_subparser_choices()) == EXPECTED_SUBCOMMANDS

    def test_every_subcommand_has_help(self):
        for name, subparser in _subparser_choices().items():
            assert subparser.description or subparser.format_usage(), name

    def test_help_lists_every_subcommand(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        for name in EXPECTED_SUBCOMMANDS:
            assert name in out

    def test_no_args_is_an_error(self):
        with pytest.raises(SystemExit):
            main([])

    def test_unknown_subcommand_errors(self):
        with pytest.raises(SystemExit):
            main(["not-a-command"])

    def test_workspace_commands_require_db(self):
        for name in ("ingest", "export", "ask", "recall", "remember", "forget"):
            with pytest.raises(SystemExit):
                main([name])
