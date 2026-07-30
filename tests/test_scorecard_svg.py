"""Scorecard bar chart: geometry, pass/fail colors, escaping."""

from mnemofold.reports import render_scorecard_svg

ROWS = [
    ("commitment_recall", 1.0, True),
    ("triage_precision", 0.62, False),
    ("budget_adherence", 0.875, True),
]


class TestScorecardSvg:
    def test_structure_and_row_count(self):
        svg = render_scorecard_svg(ROWS)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert svg.count("<text") == 3
        # each row: one value bar + one outline
        assert svg.count("<rect") == 6

    def test_pass_fail_colors(self):
        svg = render_scorecard_svg(ROWS)
        assert svg.count('fill="#2f855a"') == 2
        assert svg.count('fill="#c53030"') == 1

    def test_values_clamped_to_unit_scale(self):
        svg = render_scorecard_svg([("count_like", 17.0, True)])
        # clamped to 1.0 -> full-width bar
        assert 'width="448.0"' in svg  # 640 - 180 - 2*6

    def test_negative_clamped_to_zero(self):
        svg = render_scorecard_svg([("neg", -3.0, False)])
        assert 'width="0.0"' in svg

    def test_names_are_escaped(self):
        svg = render_scorecard_svg([("<script>x</script>", 0.5, True)])
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_empty_rows_render_frame(self):
        svg = render_scorecard_svg([])
        assert svg.startswith("<svg")
        assert "<rect" not in svg

    def test_deterministic(self):
        assert render_scorecard_svg(ROWS) == render_scorecard_svg(list(ROWS))

    def test_height_grows_with_rows(self):
        one = render_scorecard_svg(ROWS[:1])
        three = render_scorecard_svg(ROWS)
        assert 'height="36"' in one  # 2*6 + 1*(18+6)
        assert 'height="84"' in three  # 2*6 + 3*(18+6)
