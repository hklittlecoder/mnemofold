"""Drift reports between two scorecards."""

from mnemofold.evaluation import MetricResult, Scorecard, compare_scorecards


def card(scenario: str, *metrics: MetricResult) -> Scorecard:
    sc = Scorecard(scenario=scenario)
    for m in metrics:
        sc.add(m)
    return sc


class TestCompareScorecards:
    def test_identical_cards_produce_empty_diff(self):
        a = card("s", MetricResult("recall", 1.0, threshold=1.0))
        b = card("s", MetricResult("recall", 1.0, threshold=1.0))
        diff = compare_scorecards(a, b)
        assert diff["changed"] == []
        assert diff["only_in_baseline"] == []
        assert diff["only_in_candidate"] == []
        assert diff["baseline_scenario"] == "s"

    def test_value_change_reports_delta(self):
        a = card("s", MetricResult("recall", 0.9))
        b = card("s", MetricResult("recall", 0.75))
        diff = compare_scorecards(a, b)
        assert len(diff["changed"]) == 1
        change = diff["changed"][0]
        assert change["metric"] == "recall"
        assert change["baseline"] == 0.9
        assert change["candidate"] == 0.75
        assert change["delta"] == -0.15

    def test_status_flip_is_reported_even_at_equal_value(self):
        a = card("s", MetricResult("recall", 0.9, threshold=0.5))
        b = card("s", MetricResult("recall", 0.9, threshold=0.95))
        diff = compare_scorecards(a, b)
        assert diff["changed"][0]["baseline_status"] == "pass"
        assert diff["changed"][0]["candidate_status"] == "fail"

    def test_one_sided_metrics(self):
        a = card("s", MetricResult("kept", 1.0), MetricResult("dropped", 1.0))
        b = card("s", MetricResult("kept", 1.0), MetricResult("added", 1.0))
        diff = compare_scorecards(a, b)
        assert diff["only_in_baseline"] == ["dropped"]
        assert diff["only_in_candidate"] == ["added"]
        assert diff["changed"] == []

    def test_delta_quantized_to_six_decimals(self):
        a = card("s", MetricResult("m", 0.1234567))
        b = card("s", MetricResult("m", 0.1234568))
        change = compare_scorecards(a, b)["changed"][0]
        assert change["delta"] == 0.0
        assert change["baseline"] == 0.123457
        assert change["candidate"] == 0.123457

    def test_changed_metrics_sorted_by_name(self):
        a = card("s", MetricResult("zeta", 1.0), MetricResult("alpha", 1.0))
        b = card("s", MetricResult("zeta", 0.5), MetricResult("alpha", 0.5))
        names = [c["metric"] for c in compare_scorecards(a, b)["changed"]]
        assert names == ["alpha", "zeta"]
