"""Golden bytes for render_standup_markdown.

Section order, empty-section placeholders, and the citations footer are
frozen so report formatting cannot drift silently.
"""

from pathlib import Path

from mnemofold.review import StandupData, render_standup_html, render_standup_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "standup_markdown_golden.md"


def make_data() -> StandupData:
    return StandupData(
        date="2026-03-10",
        completed=["draft spec [c1]"],
        in_progress=[],
        planned=["review pass [c2]"],
        blockers=["waiting on vendor [b1]"],
        open_commitments=["ship fix [c3]"],
        overdue=["late report [c4]"],
        pending_decisions=["pick vendor [d1]"],
        citations=["c1", "c2", "c3", "c4", "d1"],
    )


class TestStandupMarkdownGolden:
    def test_matches_golden_bytes(self):
        assert render_standup_markdown(make_data()) == FIXTURE.read_text(encoding="utf-8")

    def test_empty_sections_use_placeholder(self):
        md = render_standup_markdown(make_data())
        assert "## In progress\n\n_None_" in md

    def test_citations_footer_counts(self):
        assert render_standup_markdown(make_data()).endswith("*Citations: 5*")

    def test_html_covers_the_same_content(self):
        html_out = render_standup_html(make_data())
        assert "draft spec [c1]" in html_out
        assert "late report [c4]" in html_out
        assert "2026-03-10" in html_out

    def test_regeneration_is_stable(self):
        assert render_standup_markdown(make_data()) == render_standup_markdown(make_data())
