"""Hand-computed calibration checks: clamping, ECE weighting, bin edges."""

import pytest

from mnemofold.evaluation import triage_calibration
from mnemofold.triage import TriagePriority, TriageResult


def result(item_id: str, score: float) -> TriageResult:
    return TriageResult(item_id=item_id, score=score, priority=TriagePriority.HIGH, reasons=[])


class TestCalibrationEdges:
    def test_out_of_range_scores_are_clamped(self):
        results = [result("hi", 1.4), result("lo", -0.3)]
        labels = {"hi": True, "lo": False}
        # clamped to 1.0 and 0.0 -> perfect predictions -> zero brier
        assert triage_calibration(results, labels)["brier"] == 0.0

    def test_ece_matches_hand_computation(self):
        # two bins over [0,1): scores 0.25 and 0.75, one label each
        results = [result("a", 0.25), result("b", 0.75)]
        labels = {"a": False, "b": True}
        report = triage_calibration(results, labels, bins=2)
        # bin [0.0,0.5): mean_predicted 0.25, observed 0.0 -> gap .25, weight .5
        # bin [0.5,1.0]: mean_predicted 0.75, observed 1.0 -> gap .25, weight .5
        assert report["ece"] == pytest.approx(0.25)
        # brier = ((0.25-0)^2 + (0.75-1)^2) / 2
        assert report["brier"] == pytest.approx(0.0625)

    def test_all_positive_bin(self):
        results = [result("a", 0.9), result("b", 0.95)]
        labels = {"a": True, "b": True}
        report = triage_calibration(results, labels, bins=1)
        assert len(report["bins"]) == 1
        assert report["bins"][0]["observed_rate"] == 1.0
        assert report["bins"][0]["count"] == 2

    def test_invalid_bins_rejected(self):
        with pytest.raises(ValueError):
            triage_calibration([result("a", 0.5)], {"a": True}, bins=0)
