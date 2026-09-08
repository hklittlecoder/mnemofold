"""Golden bytes for the workload heat strip renderer.

The strip encodes per-day counts as color intensity; freezing the exact
SVG keeps the intensity math and geometry from drifting unnoticed.
"""

from pathlib import Path

from mnemofold.review import render_work_strip_svg

FIXTURE = Path(__file__).parent / "fixtures" / "work_strip_golden.svg"
COUNTS = [1, 3, 2, 0, 5]


class TestWorkStripGolden:
    def test_matches_golden_bytes(self):
        assert render_work_strip_svg(COUNTS) == FIXTURE.read_text(encoding="utf-8")

    def test_one_rect_per_day(self):
        svg = render_work_strip_svg(COUNTS)
        assert svg.count("<rect") == len(COUNTS)

    def test_zero_counts_render_lightest(self):
        svg = render_work_strip_svg([0, 4])
        # zero intensity -> r=g=255, b=255 per the documented formula
        assert "rgb(255,255,255)" in svg

    def test_max_count_renders_darkest(self):
        svg = render_work_strip_svg([0, 4])
        assert "rgb(55,55,15)" in svg

    def test_empty_counts_short_svg(self):
        assert render_work_strip_svg([]) == '<svg width="600" height="40"></svg>'

    def test_regeneration_is_stable(self):
        assert render_work_strip_svg(COUNTS) == render_work_strip_svg(list(COUNTS))
