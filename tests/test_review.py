"""Tests for review module."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mnemofold.factory import WorkHistoryFactory
from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus
from mnemofold.reports import TimelineItem, assemble_report_page
from mnemofold.review import (
    StandupGenerator,
    WeeklyReview,
    WeeklyReviewGenerator,
    render_standup_html,
    render_standup_markdown,
    render_weekly_html,
    render_weekly_markdown,
    render_work_strip_svg,
)


class TestWeeklyStats:
    def _ledger(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "Write report", "2024-01-20T00:00:00+00:00"))
        ledger.add(Commitment("c2", "b", "a", "Review design", "2024-01-25T00:00:00+00:00"))
        ledger.add(Commitment("c3", "c", "a", "Deploy", "2024-01-10T00:00:00+00:00"))
        ledger.transition("c1", CommitmentStatus.DONE, "2024-01-18T12:00:00+00:00")
        return ledger

    def test_stats_include_counts(self):
        gen = WeeklyReviewGenerator(self._ledger())
        review = gen.generate("2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00")
        assert "completed_count" in review.stats
        assert "overdue_count" in review.stats
        assert "citation_count" in review.stats
        assert review.stats["completed_count"] == 1

    def test_stats_match_list_lengths(self):
        gen = WeeklyReviewGenerator(self._ledger())
        review = gen.generate("2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00")
        assert review.stats["completed_count"] == len(review.completed)
        assert review.stats["overdue_count"] == len(review.overdue)
        assert review.stats["still_open_count"] == len(review.still_open)
        assert review.stats["risk_count"] == len(review.risks)

    def test_markdown_includes_summary_section(self):
        gen = WeeklyReviewGenerator(self._ledger())
        review = gen.generate("2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00")
        md = render_weekly_markdown(review)
        assert "## Summary" in md
        assert "Completed" in md
        assert "1" in md


class TestStandupGenerator:
    def _ledger(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "Write report", "2024-01-20T00:00:00+00:00"))
        ledger.add(Commitment("c2", "b", "a", "Review design", "2024-01-25T00:00:00+00:00"))
        ledger.add(Commitment("c3", "c", "a", "Deploy", "2024-01-10T00:00:00+00:00"))
        return ledger

    def test_generate(self):
        gen = StandupGenerator(self._ledger())
        data = gen.generate("2024-01-15T00:00:00+00:00")
        assert len(data.overdue) > 0
        assert len(data.open_commitments) > 0
        assert len(data.citations) > 0

    def test_overdue_detected(self):
        gen = StandupGenerator(self._ledger())
        data = gen.generate("2024-01-15T00:00:00+00:00")
        assert any("c3" in s for s in data.overdue)

    def test_every_overdue_line_cites_commitment_id(self):
        gen = StandupGenerator(self._ledger())
        data = gen.generate("2024-01-20T00:00:00+00:00")
        for line in data.overdue:
            assert "[" in line and "]" in line
            cid = line[line.rindex("[") + 1 : line.rindex("]")]
            assert cid in data.citations

    def test_completed_items_come_from_today(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("done_yesterday", "a", "b", "Old", "2024-01-10T00:00:00+00:00"))
        ledger.add(Commitment("done_today", "a", "b", "New", "2024-01-18T00:00:00+00:00"))
        ledger.transition("done_yesterday", CommitmentStatus.DONE, "2024-01-14T10:00:00+00:00")
        ledger.transition("done_today", CommitmentStatus.DONE, "2024-01-15T09:00:00+00:00")
        gen = StandupGenerator(ledger)
        data = gen.generate("2024-01-15T12:00:00+00:00")
        assert any("done_today" in s for s in data.completed)
        assert not any("done_yesterday" in s for s in data.completed)


class TestRendering:
    def test_markdown(self):
        from mnemofold.review import StandupData

        data = StandupData(date="2024-01-15", completed=["A [m1]"], blockers=["X [m2]"])
        md = render_standup_markdown(data)
        assert "Standup" in md and "2024-01-15" in md

    def test_html(self):
        from mnemofold.review import StandupData

        data = StandupData(date="2024-01-15", completed=["Done [m1]"])
        h = render_standup_html(data)
        assert "<html" in h and "Standup" in h

    def test_html_escapes(self):
        from mnemofold.review import StandupData

        data = StandupData(date="<evil>", completed=["<script>x</script>"])
        h = render_standup_html(data)
        assert "<script>" not in h


class TestWorkStrip:
    def test_svg(self):
        svg = render_work_strip_svg([1, 3, 5, 2])
        assert svg.startswith("<svg") and "<rect" in svg

    def test_empty(self):
        assert "<svg" in render_work_strip_svg([])


class TestWeeklyReviewGenerator:
    def _ledger(self) -> CommitmentLedger:
        ledger = CommitmentLedger()
        # completed inside the window
        ledger.add(Commitment("c1", "a", "b", "Ship report", "2024-01-18T00:00:00+00:00"))
        ledger.transition("c1", CommitmentStatus.DONE, "2024-01-17T09:00:00+00:00")
        # overdue at week_end
        ledger.add(Commitment("c2", "a", "b", "Pay invoice", "2024-01-10T00:00:00+00:00"))
        # far future, open
        ledger.add(Commitment("c3", "a", "b", "Plan offsite", "2024-02-15T00:00:00+00:00"))
        # due next week
        ledger.add(Commitment("c4", "a", "b", "Review PR", "2024-01-25T00:00:00+00:00"))
        return ledger

    def _review(self) -> WeeklyReview:
        return WeeklyReviewGenerator(self._ledger()).generate(
            "2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00"
        )

    def test_completed_from_history_in_window(self):
        review = self._review()
        assert any("c1" in line for line in review.completed)
        assert "c1" in review.citations

    def test_transition_outside_window_not_completed(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("x", "a", "b", "Late", "2024-01-10T00:00:00+00:00"))
        ledger.transition("x", CommitmentStatus.DONE, "2024-02-01T00:00:00+00:00")
        review = WeeklyReviewGenerator(ledger).generate(
            "2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00"
        )
        assert review.completed == []

    def test_overdue_listed_as_of_week_end(self):
        review = self._review()
        assert any("c2" in line for line in review.overdue)
        assert not any("c3" in line for line in review.overdue)

    def test_due_next_week_excludes_overdue(self):
        review = self._review()
        assert any("c4" in line for line in review.due_next_week)
        # c2 is overdue, not "due next week"
        assert not any("c2" in line for line in review.due_next_week)

    def test_still_open_includes_active_statuses(self):
        review = self._review()
        joined = " ".join(review.still_open)
        assert "c2" in joined and "c3" in joined and "c4" in joined
        assert "c1" not in joined  # done

    def test_risks_surface_overdue(self):
        review = self._review()
        assert review.risks and any("c2" in line for line in review.risks)

    def test_every_line_cites_an_id(self):
        review = self._review()
        assert review.citations
        assert all(cid for cid in review.citations)

    def test_invalid_window_yields_empty_completed(self):
        review = WeeklyReviewGenerator(self._ledger()).generate("bad", "worse")
        assert review.completed == []

    def test_deterministic(self):
        first = self._review()
        second = self._review()
        assert first.completed == second.completed
        assert first.overdue == second.overdue
        assert first.citations == second.citations


class TestWeeklyRendering:
    def _review(self) -> WeeklyReview:
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "Ship report", "2024-01-18T00:00:00+00:00"))
        ledger.transition("c1", CommitmentStatus.DONE, "2024-01-17T09:00:00+00:00")
        ledger.add(Commitment("c2", "a", "b", "Pay invoice", "2024-01-10T00:00:00+00:00"))
        return WeeklyReviewGenerator(ledger).generate(
            "2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00"
        )

    def test_markdown_has_all_sections(self):
        markdown = render_weekly_markdown(self._review())
        assert markdown.startswith("# Weekly Review")
        for heading in (
            "## Completed",
            "## Overdue",
            "## Still open",
            "## Due next week",
            "## Risks",
        ):
            assert heading in markdown

    def test_markdown_shows_counts_and_none(self):
        markdown = render_weekly_markdown(self._review())
        assert "## Completed (1)" in markdown
        assert "## Due next week (0)" in markdown
        assert "_None_" in markdown

    def test_html_is_self_contained_and_escaped(self):
        review = self._review()
        review.completed.append("<script>alert(1)</script> [evil]")
        page = render_weekly_html(review)
        assert page.startswith("<!DOCTYPE html>")
        assert "<script>alert" not in page
        assert "&lt;script&gt;" in page

    def test_rendering_is_deterministic(self):
        assert render_weekly_markdown(self._review()) == render_weekly_markdown(self._review())
        assert render_weekly_html(self._review()) == render_weekly_html(self._review())


class TestWeeklyWindowEdges:
    WINDOW = ("2024-01-15T00:00:00+00:00", "2024-01-22T00:00:00+00:00")

    def _ledger_with_done_at(self, ts: str) -> CommitmentLedger:
        ledger = CommitmentLedger()
        ledger.add(
            Commitment(
                "c1",
                "a",
                "b",
                "task",
                "2024-01-18T00:00:00+00:00",
                created_at="2024-01-10T00:00:00+00:00",
            )
        )
        ledger.transition("c1", CommitmentStatus.DONE, ts)
        return ledger

    def test_start_boundary_inclusive(self):
        review = WeeklyReviewGenerator(
            self._ledger_with_done_at("2024-01-15T00:00:00+00:00")
        ).generate(*self.WINDOW)
        assert len(review.completed) == 1

    def test_end_boundary_exclusive(self):
        review = WeeklyReviewGenerator(
            self._ledger_with_done_at("2024-01-22T00:00:00+00:00")
        ).generate(*self.WINDOW)
        assert review.completed == []

    def test_naive_timestamps_read_as_utc(self):
        review = WeeklyReviewGenerator(self._ledger_with_done_at("2024-01-17T00:00:00")).generate(
            *self.WINDOW
        )
        assert len(review.completed) == 1

    def test_in_progress_counts_as_open(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("w1", "a", "b", "wip task", "2024-02-01T00:00:00+00:00"))
        ledger.transition("w1", CommitmentStatus.IN_PROGRESS, "2024-01-16T00:00:00+00:00")
        review = WeeklyReviewGenerator(ledger).generate(*self.WINDOW)
        assert any("w1" in line for line in review.still_open)

    def test_due_next_week_boundary(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("in7", "a", "b", "task", "2024-01-29T00:00:00+00:00"))
        ledger.add(Commitment("out8", "a", "b", "task", "2024-01-30T00:00:00+00:00"))
        review = WeeklyReviewGenerator(ledger).generate(*self.WINDOW)
        joined = " ".join(review.due_next_week)
        assert "in7" in joined
        assert "out8" not in joined

    def test_risk_line_for_imminent_deadline(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("soon", "a", "b", "tight task", "2024-01-22T12:00:00+00:00"))
        review = WeeklyReviewGenerator(ledger).generate(*self.WINDOW)
        assert any("due within a day" in line and "soon" in line for line in review.risks)


class TestStandupCompleted:
    def _ledger(self) -> CommitmentLedger:
        ledger = CommitmentLedger()
        ledger.add(Commitment("d1", "a", "b", "done today", "2024-01-14T00:00:00+00:00"))
        ledger.transition("d1", CommitmentStatus.DONE, "2024-01-15T09:30:00+00:00")
        ledger.add(Commitment("d2", "a", "b", "done earlier", "2024-01-10T00:00:00+00:00"))
        ledger.transition("d2", CommitmentStatus.DONE, "2024-01-12T09:30:00+00:00")
        return ledger

    def test_completed_lists_same_day_transitions(self):
        data = StandupGenerator(self._ledger()).generate("2024-01-15T18:00:00+00:00")
        assert any("d1" in line for line in data.completed)
        assert not any("d2" in line for line in data.completed)
        assert "d1" in data.citations

    def test_pending_decisions_passthrough(self):
        data = StandupGenerator(self._ledger()).generate(
            "2024-01-15T18:00:00+00:00", pending_decisions=["pick vendor [dec1]"]
        )
        assert data.pending_decisions == ["pick vendor [dec1]"]

    def test_invalid_today_raises(self):
        with pytest.raises(ValueError, match="invalid standup date"):
            StandupGenerator(self._ledger()).generate("garbage")

    def test_day_window_follows_local_zone_not_utc(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("early", "a", "b", "morning task", "2024-01-14T00:00:00+00:00"))
        ledger.transition("early", CommitmentStatus.DONE, "2024-01-15T06:00:00+00:00")
        ledger.add(Commitment("late", "a", "b", "next utc day task", "2024-01-14T00:00:00+00:00"))
        ledger.transition("late", CommitmentStatus.DONE, "2024-01-16T06:00:00+00:00")
        # 23:30 at -05:00: the local day is 2024-01-15 and spans
        # [2024-01-15T05:00Z, 2024-01-16T05:00Z)
        data = StandupGenerator(ledger).generate("2024-01-15T23:30:00-05:00")
        completed = " ".join(data.completed)
        assert "early" in completed
        assert "late" not in completed


class TestFactoryDrivenReports:
    """Reports driven by the synthetic factory's planted commitments.

    Every number here is measured on seeded synthetic data (seed 42,
    60 days) — expectations are computed from the same ledger, never
    copied from implementation internals.
    """

    NOW = "2025-02-15T00:00:00+00:00"

    def _ledger(self) -> tuple[CommitmentLedger, int]:
        factory = WorkHistoryFactory(seed=42, days=60)
        factory.generate()
        ledger = CommitmentLedger()
        planted = [p for p in factory.planted_items() if p.kind == "commitment"]
        for p in planted:
            data = p.data
            ledger.add(
                Commitment(
                    p.item_id,
                    data["owed_by"],
                    data["owed_to"],
                    data["description"],
                    data["due_date"],
                )
            )
        return ledger, len(planted)

    def test_standup_overdue_matches_direct_computation(self):
        ledger, planted = self._ledger()
        assert planted >= 2
        data = StandupGenerator(ledger).generate(self.NOW)
        expected = [c for c in ledger.all_commitments() if c.is_overdue(self.NOW)]
        assert len(data.overdue) == len(expected)
        for c in expected:
            assert any(c.commitment_id in line for line in data.overdue)

    def test_weekly_review_covers_all_planted_commitments(self):
        ledger, planted = self._ledger()
        review = WeeklyReviewGenerator(ledger).generate(
            "2024-12-31T00:00:00+00:00", "2025-03-02T00:00:00+00:00"
        )
        # nothing transitioned to done, so completed is empty and every
        # planted commitment is still open
        assert review.completed == []
        assert len(review.still_open) == planted
        cited = set(review.citations)
        assert {c.commitment_id for c in ledger.all_commitments()} <= cited

    def test_rendered_reports_are_deterministic(self):
        ledger, _ = self._ledger()
        data = StandupGenerator(ledger).generate(self.NOW)
        assert render_standup_markdown(data) == render_standup_markdown(data)
        assert render_standup_html(data) == render_standup_html(data)
        review = WeeklyReviewGenerator(ledger).generate(
            "2025-02-01T00:00:00+00:00", "2025-02-08T00:00:00+00:00"
        )
        assert render_weekly_markdown(review) == render_weekly_markdown(review)
        assert render_weekly_html(review) == render_weekly_html(review)

    def test_assembled_page_from_ledger_timeline(self):
        ledger, _ = self._ledger()
        items = []
        for c in ledger.all_commitments():
            due = date.fromisoformat(c.due_date[:10])
            status = "overdue" if c.is_overdue(self.NOW) else "open"
            items.append(
                TimelineItem(
                    label=c.description, start=due - timedelta(days=7), end=due, status=status
                )
            )
        page = assemble_report_page(
            "Commitment timeline",
            timeline_items=items,
            run_metadata={"seed": "42", "days": "60"},
        )
        assert page.startswith("<!DOCTYPE html>")
        assert "<svg" in page
        assert "Run metadata" in page
        assert ">seed<" in page
