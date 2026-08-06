"""Scorecard -> SVG row mapping: attainment, clamping, honest colors."""

from mnemofold.evaluation import MetricResult, Scorecard, scorecard_svg_rows


class TestScorecardSvgRows:
    def test_attainment_relative_to_threshold(self):
        card = Scorecard(scenario="s")
        card.add(MetricResult("recall", 0.5, threshold=1.0))
        rows = scorecard_svg_rows(card)
        # 0.5 attainment, and below threshold -> the bar renders red
        assert rows == [("recall", 0.5, False)]

    def test_full_attainment_passes(self):
        card = Scorecard(scenario="s")
        card.add(MetricResult("recall", 1.0, threshold=1.0))
        assert scorecard_svg_rows(card) == [("recall", 1.0, True)]

    def test_over_threshold_clamped_to_one(self):
        card = Scorecard(scenario="s")
        card.add(MetricResult("events", 1500.0, threshold=100.0))
        assert scorecard_svg_rows(card)[0][1] == 1.0

    def test_failed_metric_keeps_fail_color(self):
        card = Scorecard(scenario="s")
        card.add(MetricResult("recall", 0.4, threshold=0.9))
        name, value, passed = scorecard_svg_rows(card)[0]
        assert (name, round(value, 6), passed) == ("recall", round(0.4 / 0.9, 6), False)

    def test_unthresholded_metric_uses_raw_value_clamped(self):
        card = Scorecard(scenario="s")
        card.add(MetricResult("count", 42.0))
        card.add(MetricResult("ratio", 0.25))
        rows = dict((name, (value, passed)) for name, value, passed in scorecard_svg_rows(card))
        assert rows["count"] == (1.0, True)  # clamped
        assert rows["ratio"] == (0.25, True)

    def test_row_order_matches_metric_order(self):
        card = Scorecard(scenario="s")
        for name in ("zeta", "alpha", "mid"):
            card.add(MetricResult(name, 1.0))
        assert [r[0] for r in scorecard_svg_rows(card)] == ["zeta", "alpha", "mid"]

    def test_empty_card(self):
        assert scorecard_svg_rows(Scorecard(scenario="s")) == []
