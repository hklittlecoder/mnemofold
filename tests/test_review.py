"""Tests for review module."""

from __future__ import annotations

from mnemofold.ledger import Commitment, CommitmentLedger
from mnemofold.review import (
    StandupGenerator,
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
