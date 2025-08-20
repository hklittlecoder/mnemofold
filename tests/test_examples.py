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
