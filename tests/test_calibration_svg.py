"""Calibration reliability diagram: geometry, clamping, determinism."""

from mnemofold.evaluation import calibration_report
from mnemofold.reports import render_calibration_svg


class TestCalibrationSvg:
    def test_svg_structure(self):
        svg = render_calibration_svg([(0.2, 0.3), (0.8, 0.7)])
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert "<polyline" in svg
        assert svg.count("<circle") == 2
        assert "predicted" in svg and "observed" in svg

    def test_extreme_points_map_to_canvas_corners(self):
        svg = render_calibration_svg([(0.0, 0.0), (1.0, 1.0)])
        # pad=40, size=320 -> span 240; (0,0) -> 40,280 and (1,1) -> 280,40
        assert "40.0,280.0" in svg
        assert "280.0,40.0" in svg

    def test_out_of_range_points_are_clamped(self):
        svg = render_calibration_svg([(1.5, -0.5)])
        assert "280.0,280.0" in svg

    def test_empty_points_still_renders_axes(self):
        svg = render_calibration_svg([])
        assert "<polyline" not in svg
        assert "<circle" not in svg
        assert "<line" in svg  # the diagonal reference remains

    def test_rendering_is_deterministic(self):
        points = [(0.1, 0.2), (0.5, 0.45), (0.9, 0.95)]
        assert render_calibration_svg(points) == render_calibration_svg(points)

    def test_renders_a_real_calibration_report(self):
        probs = [0.05, 0.15, 0.25, 0.55, 0.65, 0.95, 0.9, 0.85]
        outcomes = [False, False, True, True, False, True, True, True]
        bins = calibration_report(probs, outcomes, bins=5)
        points = [(b.mean_predicted, b.observed_rate) for b in bins]
        svg = render_calibration_svg(points)
        assert svg.count("<circle") == len(bins)
