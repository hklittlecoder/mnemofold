"""Noise sweep: measured recall per level, honest and deterministic."""

import pytest

from mnemofold.evaluation import ScenarioConfig, run_noise_sweep


@pytest.fixture(scope="module")
def sweep():
    return run_noise_sweep(ScenarioConfig(seed=42, days=30), noise_levels=(0.0, 0.5))


class TestNoiseSweep:
    def test_results_ordered_by_level(self, sweep):
        assert [r.scorecard.details["noise_level"] for r in sweep] == [0.0, 0.5]

    def test_scenario_names_encode_level(self, sweep):
        assert [r.scorecard.scenario for r in sweep] == [
            "noise-0.0-seed42",
            "noise-0.5-seed42",
        ]

    def test_clean_recall_is_perfect(self, sweep):
        assert sweep[0].measurements["commitment_recall"] == 1.0

    def test_noisy_recall_measured_in_range(self, sweep):
        recall = sweep[1].measurements["commitment_recall"]
        assert 0.0 <= recall <= 1.0
        # informational metric: no threshold, card still passes
        assert sweep[1].scorecard.overall_pass()

    def test_ground_truth_is_labeled_synthetic(self, sweep):
        for result in sweep:
            assert "synthetic" in result.scorecard.details["ground_truth"]

    def test_sweep_is_deterministic(self, sweep):
        again = run_noise_sweep(ScenarioConfig(seed=42, days=30), noise_levels=(0.0, 0.5))
        assert [r.scorecard.to_dict() for r in again] == [r.scorecard.to_dict() for r in sweep]
