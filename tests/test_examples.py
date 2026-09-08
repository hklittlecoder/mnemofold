"""Smoke tests: examples run offline, deterministically, and pass.

Each example's ``main()`` is loaded straight from its ``run.py`` and
executed in-process; examples must not touch the network, need no GPU,
and write nothing outside temporary directories they manage themselves.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_example(name: str):
    """Import examples/<name>/run.py as a module."""
    path = EXAMPLES / name / "run.py"
    spec = importlib.util.spec_from_file_location(f"example_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHistoryWorkstreamExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("history_workstream").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_measured_recall_is_perfect(self, capsys):
        load_example("history_workstream").main()
        out = capsys.readouterr().out
        assert "commitment recall" in out
        assert "1.0000" in out

    def test_graph_invariants_reported(self, capsys):
        load_example("history_workstream").main()
        out = capsys.readouterr().out
        assert "dangling=0" in out
        assert "acyclic=True" in out

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("history_workstream")
        module.main()
        first = capsys.readouterr().out
        module.main()
        second = capsys.readouterr().out
        assert first == second


class TestContradictionMonthExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("contradiction_month").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_asof_answers_all_correct(self, capsys):
        load_example("contradiction_month").main()
        out = capsys.readouterr().out
        line = next(line for line in out.splitlines() if "as-of answers correct" in line)
        correct, total = line.split(":")[1].split()[0].split("/")
        assert correct == total
        assert int(total) > 0

    def test_verified_source_wins_overlap(self, capsys):
        load_example("contradiction_month").main()
        out = capsys.readouterr().out
        assert "winner value: bob" in out

    def test_cascade_protects_held_node(self, capsys):
        load_example("contradiction_month").main()
        out = capsys.readouterr().out
        assert "'held'" in out  # blocked list contains the protected node
        assert "resurrection blocked by tombstone: True" in out

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("contradiction_month")
        module.main()
        first = capsys.readouterr().out
        module.main()
        assert first == capsys.readouterr().out


class TestFoldingDemoExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("folding_demo").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_second_fold_is_idempotent(self, capsys):
        load_example("folding_demo").main()
        out = capsys.readouterr().out
        assert "second fold idempotent: merges=0 new_semantic=0" in out

    def test_workflow_mined_into_playbook(self, capsys):
        load_example("folding_demo").main()
        out = capsys.readouterr().out
        assert "draft -> review -> publish" in out
        assert "approved playbooks: ['pb-release']" in out

    def test_report_markdown_embedded(self, capsys):
        load_example("folding_demo").main()
        out = capsys.readouterr().out
        assert "# Fold Report nightly-demo" in out

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("folding_demo")
        module.main()
        first = capsys.readouterr().out
        module.main()
        assert first == capsys.readouterr().out


@pytest.mark.slow
class TestAssistantWeekExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("assistant_week").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_workspace_and_triage_reported(self, capsys):
        load_example("assistant_week").main()
        out = capsys.readouterr().out
        assert "workspace: events=" in out
        assert "triage: ranked=" in out

    def test_suite_passes_and_aggregate_printed(self, capsys):
        load_example("assistant_week").main()
        out = capsys.readouterr().out
        assert "suite overall_pass: True" in out
        assert "aggregate commitment_recall: 1.0000" in out
        assert "aggregate privacy_violations: 0.0000" in out

    def test_context_pack_within_budget(self, capsys):
        load_example("assistant_week").main()
        out = capsys.readouterr().out
        line = next(line for line in out.splitlines() if "context pack:" in line)
        used, budget = line.split("tokens")[0].split()[-1].split("/")
        assert int(used) <= int(budget)

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("assistant_week")
        module.main()
        first = capsys.readouterr().out
        module.main()
        assert first == capsys.readouterr().out


class TestLifecyclePrivacyExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("lifecycle_privacy").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_privacy_and_audit_checks_reported(self, capsys):
        load_example("lifecycle_privacy").main()
        out = capsys.readouterr().out
        for marker in (
            "sealed_hides_email",
            "vault_unseal_restores",
            "preview_plans_the_note",
            "forgotten_not_recallable",
            "integrity_ok",
        ):
            assert marker in out

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("lifecycle_privacy")
        module.main()
        first = capsys.readouterr().out
        module.main()
        second = capsys.readouterr().out
        assert first == second


class TestPlaybookLifecycleExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("playbook_lifecycle").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_lifecycle_checks_reported(self, capsys):
        load_example("playbook_lifecycle").main()
        out = capsys.readouterr().out
        for marker in (
            "recurrence_mined",
            "denied_run_blocked",
            "approved_run_completed",
            "run_count_incremented",
            "revision_created",
            "diff_shows_removed_step",
        ):
            assert marker in out

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("playbook_lifecycle")
        module.main()
        first = capsys.readouterr().out
        module.main()
        second = capsys.readouterr().out
        assert first == second


class TestAssistantWeekRoleSlices:
    def test_role_slices_reported(self, capsys):
        rc = load_example("assistant_week").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "role slice commitments[role:" in out
        assert "recall=" in out

    @pytest.mark.slow
    def test_role_slice_output_deterministic(self, capsys):
        module = load_example("assistant_week")
        module.main()
        first = capsys.readouterr().out
        module.main()
        assert capsys.readouterr().out == first


class TestIntegrityAuditExample:
    def test_runs_and_reports_ok(self, capsys):
        rc = load_example("integrity_audit").main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "RESULT: OK" in out

    def test_all_audit_checks_reported(self, capsys):
        load_example("integrity_audit").main()
        out = capsys.readouterr().out
        for marker in (
            "healthy_verify_ok",
            "tamper_detected",
            "original_trace_intact",
            "forgotten_not_recallable",
            "resurrection_detected",
            "repaired_verify_ok",
            "bundle_events_match",
        ):
            assert marker in out

    @pytest.mark.slow
    def test_output_is_deterministic(self, capsys):
        module = load_example("integrity_audit")
        module.main()
        first = capsys.readouterr().out
        module.main()
        assert capsys.readouterr().out == first
