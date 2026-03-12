"""Robustness scenario: honest measured numbers on sliced histories."""

import pytest

from mnemofold.evaluation import ScenarioConfig, run_robustness_scenario


@pytest.fixture(scope="module")
def result():
    return run_robustness_scenario(ScenarioConfig(seed=42, days=30))


class TestRobustnessScenario:
    def test_measures_both_histories(self, result):
        details = result.scorecard.details
        assert 0.0 <= details["full_recall"] <= 1.0
        assert 0.0 <= details["mail_only_recall"] <= 1.0
        assert "synthetic" in details["ground_truth"]

    def test_full_history_recovers_everything(self, result):
        values = {m.name: m.value for m in result.scorecard.metrics}
        assert values["full_commitment_recall"] == 1.0
        assert result.scorecard.overall_pass()

    def test_mail_only_recall_is_reported_not_assumed(self, result):
        # the slice number is measured; the test only pins its range and
        # the internal consistency of details vs metrics
        values = {m.name: m.value for m in result.scorecard.metrics}
        assert values["mail_only_commitment_recall"] == result.scorecard.details["mail_only_recall"]
        assert 0.0 <= values["mail_only_commitment_recall"] <= 1.0

    def test_recall_gap_matches_components(self, result):
        d = result.scorecard.details
        assert d["recall_gap"] == round(d["full_recall"] - d["mail_only_recall"], 6)

    def test_measurements_carry_both_runs(self, result):
        assert "full" in result.measurements
        assert "mail_only" in result.measurements
        assert result.measurements["mail_only"]["planted"] >= 0

    def test_deterministic_double_run(self):
        cfg = ScenarioConfig(seed=7, days=30)
        a = run_robustness_scenario(cfg).scorecard.to_dict()
        b = run_robustness_scenario(cfg).scorecard.to_dict()
        assert a == b
