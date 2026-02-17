"""Burndown chart geometry, labels, and determinism."""

from mnemofold.reports import render_burndown_svg

SERIES = [
    {"day": "2026-03-01", "created": 0, "resolved": 0, "open": 0},
    {"day": "2026-03-02", "created": 2, "resolved": 1, "open": 1},
    {"day": "2026-03-03", "created": 4, "resolved": 4, "open": 0},
]


class TestBurndownSvg:
    def test_structure(self):
        svg = render_burndown_svg(SERIES)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert svg.count("<polyline") == 2

    def test_coordinate_geometry(self):
        # width 640, height 200, pad 40 -> inner 560x120; scale = 4
        svg = render_burndown_svg(SERIES)
        assert 'points="40.0,160.0 320.0,100.0 600.0,40.0"' in svg  # created
        assert 'points="40.0,160.0 320.0,130.0 600.0,40.0"' in svg  # resolved

    def test_day_labels_and_scale(self):
        svg = render_burndown_svg(SERIES)
        assert "2026-03-01" in svg
        assert "2026-03-03" in svg
        assert ">4</text>" in svg

    def test_empty_series_renders_frame_only(self):
        svg = render_burndown_svg([])
        assert "<polyline" not in svg
        assert "<rect" in svg
        assert svg.endswith("</svg>")

    def test_single_point_does_not_divide_by_zero(self):
        # one point: x collapses to pad; created=2 sets the scale, so
        # created sits on the top edge and resolved halfway down
        svg = render_burndown_svg([SERIES[1]])
        assert svg.count("<polyline") == 2
        assert 'points="40.0,40.0"' in svg
        assert 'points="40.0,100.0"' in svg

    def test_deterministic(self):
        assert render_burndown_svg(SERIES) == render_burndown_svg(list(SERIES))

    def test_hostile_day_labels_escaped(self):
        hostile = [{"day": "<script>x</script>", "created": 1, "resolved": 0}]
        svg = render_burndown_svg(hostile)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_renders_ledger_series(self):
        from mnemofold.ledger import Commitment, CommitmentLedger

        ledger = CommitmentLedger()
        ledger.add(
            Commitment(
                commitment_id="c1",
                owed_by="a",
                owed_to="b",
                description="d",
                due_date="2026-03-20T12:00:00+00:00",
                created_at="2026-03-01T09:00:00+00:00",
            )
        )
        svg = render_burndown_svg(ledger.burndown_series("2026-03-01", 3))
        assert svg.count("<polyline") == 2
