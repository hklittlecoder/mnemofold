"""Tests for review module."""

from __future__ import annotations

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus
from mnemofold.review import (
    StandupGenerator,
    WeeklyReview,
    WeeklyReviewGenerator,
    render_standup_html,
    render_standup_markdown,
    render_work_strip_svg,
)


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
