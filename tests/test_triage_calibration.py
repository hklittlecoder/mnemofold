"""Triage calibration: Brier + ECE over planted labels."""

from mnemofold.evaluation import triage_calibration
from mnemofold.triage import TriagePriority, TriageResult


def result(item_id: str, score: float) -> TriageResult:
    return TriageResult(item_id=item_id, score=score, priority=TriagePriority.HIGH, reasons=[])


class TestTriageCalibration:
    def test_perfect_scorer_has_zero_brier(self):
        results = [result("a", 1.0), result("b", 0.0)]
        labels = {"a": True, "b": False}
        report = triage_calibration(results, labels)
        assert report["labeled"] == 2
        assert report["brier"] == 0.0
        assert report["ece"] == 0.0

    def test_inverted_scorer_has_worst_brier(self):
        results = [result("a", 1.0), result("b", 0.0)]
        labels = {"a": False, "b": True}
        assert triage_calibration(results, labels)["brier"] == 1.0

    def test_unlabeled_items_are_skipped_and_counted(self):
        results = [result("a", 0.8), result("ghost", 0.5)]
        report = triage_calibration(results, {"a": True})
        assert report["labeled"] == 1
        assert report["unlabeled"] == 1

    def test_empty_inputs(self):
        report = triage_calibration([], {})
        assert report == {
            "labeled": 0,
            "unlabeled": 0,
            "brier": 0.0,
            "ece": 0.0,
            "bins": [],
        }

    def test_bins_partition_the_labeled_items(self):
        results = [result(f"i{i}", i / 10) for i in range(11)]
        labels = {f"i{i}": i >= 5 for i in range(11)}
        report = triage_calibration(results, labels, bins=5)
        assert sum(b["count"] for b in report["bins"]) == 11
        assert all(0.0 <= b["observed_rate"] <= 1.0 for b in report["bins"])

    def test_deterministic(self):
        results = [result("a", 0.7), result("b", 0.2)]
        labels = {"a": True, "b": False}
        assert triage_calibration(results, labels) == triage_calibration(results, labels)
