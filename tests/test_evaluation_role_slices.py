"""Per-role commitment slices over synthetic planted ground truth.

Slice runs are module-scoped fixtures: each one drives the full
factory -> ingest -> ledger pipeline, so the suite pays for it once.
"""

import pytest

from mnemofold.evaluation import (
    ScenarioConfig,
    run_commitment_scenario,
    run_role_slices,
)


@pytest.fixture(scope="module")
def slices_42():
    return run_role_slices(ScenarioConfig(seed=42, days=60))


@pytest.fixture(scope="module")
def slices_7():
    return run_role_slices(ScenarioConfig(seed=7, days=45))


class TestRoleSlices:
    def test_slices_sorted_and_cover_planted_total(self, slices_42):
        names = [r.scorecard.scenario for r in slices_42]
        assert names == sorted(names)
        assert names, "at least one role must own planted commitments"
        total = sum(r.measurements["planted"] for r in slices_42)
        whole = run_commitment_scenario(ScenarioConfig(seed=42, days=60)).measurements["planted"]
        assert total == whole

    def test_every_role_slice_recovers_its_commitments(self, slices_42):
        for result in slices_42:
            assert result.scorecard.overall_pass(), result.scorecard.scenario
            values = {m.name: m.value for m in result.scorecard.metrics}
            assert values["role_commitment_recall"] == 1.0

    def test_scenario_names_carry_the_role(self, slices_7):
        valid = {"product_manager", "engineer", "researcher", "designer"}
        for result in slices_7:
            scenario = result.scorecard.scenario
            assert "[role:" in scenario
            role = scenario.split("[role:", 1)[1].split("]", 1)[0]
            assert role in valid

    def test_details_describe_synthetic_ground_truth(self, slices_7):
        assert "synthetic" in slices_7[0].scorecard.details["ground_truth"]
