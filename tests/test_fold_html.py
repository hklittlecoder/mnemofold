"""Self-contained HTML rendering of fold reports."""

from mnemofold.fold import FoldReport, MergeResult


def make_report() -> FoldReport:
    return FoldReport(
        fold_id="fold_001",
        timestamp="2026-03-02T02:00:00+00:00",
        items_before=5,
        items_after=3,
        merges=[
            MergeResult(
                kept_id="m1",
                removed_id="m2",
                reason="near-duplicate",
                similarity=0.91,
                provenance=["e1", "e2"],
            )
        ],
        rejected=[{"a": "m3", "b": "m4", "similarity": 0.42, "reason": "below threshold"}],
        new_semantic=["s1"],
        recurrence_proposals=[{"name": "weekly release", "support": 3}],
    )


class TestFoldHtml:
    def test_page_contains_identity_and_sections(self):
        html = make_report().to_html()
        assert html.startswith("<!DOCTYPE html>")
        assert "fold_001" in html
        for heading in (
            "Summary",
            "Merges",
            "Rejected candidates",
            "New semantic items",
            "Recurrence proposals",
        ):
            assert heading in html

    def test_merge_and_reject_rows_are_present(self):
        html = make_report().to_html()
        assert "<td>m1</td>" in html
        assert "<td>m2</td>" in html
        assert "0.91" in html
        assert "below threshold" in html
        assert "weekly release" in html

    def test_hostile_text_is_escaped(self):
        report = make_report()
        report.merges[0].reason = "<script>alert('x')</script>"
        report.new_semantic = ["<img src=x onerror=alert(1)>"]
        html = report.to_html()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<img src=x" not in html

    def test_rendering_is_deterministic(self):
        assert make_report().to_html() == make_report().to_html()

    def test_empty_report_still_renders(self):
        html = FoldReport(fold_id="fold_empty", timestamp="t0").to_html()
        assert "fold_empty" in html
        assert "<!DOCTYPE html>" in html
        assert "merges: 0" in html
