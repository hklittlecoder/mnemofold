"""Golden bytes for render_weekly_markdown.

Summary block, section order, empty-section placeholders and the
citations footer are frozen; formatting drift fails here deliberately.
"""

from pathlib import Path

from mnemofold.review import WeeklyReview, render_weekly_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "weekly_review_markdown_golden.md"


def make_review() -> WeeklyReview:
    return WeeklyReview(
        week_start="2026-03-02",
        week_end="2026-03-09",
        completed=["draft spec [c1]"],
        overdue=["late report (due 2026-03-05T17:00:00+00:00) [c2]"],
        still_open=["review pass [c3]", "ship fix [c4]"],
        due_next_week=["vendor pick [c5]"],
        risks=["late report risk [c2]"],
        citations=["c1", "c2", "c3", "c4", "c5"],
        stats={
            "completed_count": 1,
            "overdue_count": 1,
            "still_open_count": 2,
            "due_next_week_count": 1,
            "risk_count": 1,
            "citation_count": 5,
        },
    )


class TestWeeklyMarkdownGolden:
    def test_matches_golden_bytes(self):
        assert render_weekly_markdown(make_review()) == FIXTURE.read_text(encoding="utf-8")

    def test_without_stats_no_summary_section(self):
        review = make_review()
        review.stats = {}
        assert "## Summary" not in render_weekly_markdown(review)

    def test_regeneration_is_stable(self):
        assert render_weekly_markdown(make_review()) == render_weekly_markdown(make_review())
