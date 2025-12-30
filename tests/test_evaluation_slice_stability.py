"""Role and project slices must agree with each other and with reruns."""

import pytest

from mnemofold.evaluation import (
    ScenarioConfig,
    aggregate_scorecards,
    run_commitment_slices,
    run_role_slices,
)

CFG = ScenarioConfig(seed=7, days=45)


@pytest.fixture(scope="module")
def first_run():
    return run_role_slices(CFG)


class TestSliceStability:
    def test_role_and_project_totals_agree(self, first_run):
        role_total = sum(r.measurements["planted"] for r in first_run)
        project_total = sum(r.measurements["planted"] for r in run_commitment_slices(CFG))
        assert role_total == project_total

    def test_double_run_is_identical(self, first_run):
        first = [r.scorecard.to_dict() for r in first_run]
        second = [r.scorecard.to_dict() for r in run_role_slices(CFG)]
        assert first == second

    def test_role_slice_aggregate_passes(self, first_run):
        agg = aggregate_scorecards([r.scorecard for r in first_run])
        assert agg.scenario == "aggregate"
        values = {m.name: m.value for m in agg.metrics}
        assert values["role_commitment_recall"] == 1.0
        assert agg.overall_pass()
