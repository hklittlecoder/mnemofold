"""Tests for commitment ledger."""

from __future__ import annotations

import json

import pytest

from mnemofold.ledger import (
    VALID_TRANSITIONS,
    Commitment,
    CommitmentLedger,
    CommitmentStatus,
    Nudge,
)


class TestCommitmentStatus:
    def test_all_statuses_have_transitions(self):
        for status in CommitmentStatus:
            assert status in VALID_TRANSITIONS

    def test_terminal_statuses_have_no_outgoing(self):
        assert len(VALID_TRANSITIONS[CommitmentStatus.DONE]) == 0
        assert len(VALID_TRANSITIONS[CommitmentStatus.CANCELLED]) == 0
        assert len(VALID_TRANSITIONS[CommitmentStatus.SUPERSEDED]) == 0


class TestCommitment:
    def test_create(self):
        c = Commitment(
            commitment_id="c1",
            owed_by="alice",
            owed_to="bob",
            description="Deliver report",
            due_date="2024-03-01T00:00:00+00:00",
        )
        assert c.status == CommitmentStatus.OPEN
        assert c.commitment_id == "c1"

    def test_can_transition_open_to_in_progress(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00")
        assert c.can_transition_to(CommitmentStatus.IN_PROGRESS)

    def test_cannot_transition_done_to_open(self):
        c = Commitment(
            "c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", status=CommitmentStatus.DONE
        )
        assert not c.can_transition_to(CommitmentStatus.OPEN)

    def test_not_overdue_before_deadline(self):
        c = Commitment("c1", "a", "b", "d", "2024-06-01T00:00:00+00:00")
        assert not c.is_overdue("2024-01-01T00:00:00+00:00")

    def test_overdue_after_deadline(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00")
        assert c.is_overdue("2024-06-01T00:00:00+00:00")

    def test_grace_period(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00")
        # 1 hour after deadline with 2h grace = not overdue
        assert not c.is_overdue("2024-01-01T01:00:00+00:00", grace_hours=2.0)
        # 3 hours after deadline with 2h grace = overdue
        assert c.is_overdue("2024-01-01T03:00:00+00:00", grace_hours=2.0)

    def test_done_not_overdue(self):
        c = Commitment(
            "c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", status=CommitmentStatus.DONE
        )
        assert not c.is_overdue("2025-01-01T00:00:00+00:00")

    def test_days_until_due(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-11T00:00:00+00:00")
        days = c.days_until_due("2024-01-01T00:00:00+00:00")
        assert days == pytest.approx(10.0)


class TestCommitmentLedger:
    def test_add_and_get(self):
        ledger = CommitmentLedger()
        c = Commitment("c1", "alice", "bob", "Report", "2024-03-01T00:00:00+00:00")
        ledger.add(c)
        assert ledger.get("c1") is not None
        assert ledger.total_count() == 1

    def test_valid_transition(self):
        ledger = CommitmentLedger()
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00")
        ledger.add(c)
        assert ledger.transition("c1", CommitmentStatus.IN_PROGRESS, "2024-01-02T00:00:00+00:00")
        assert ledger.get("c1").status == CommitmentStatus.IN_PROGRESS

    def test_invalid_transition_rejected(self):
        ledger = CommitmentLedger()
        c = Commitment(
            "c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", status=CommitmentStatus.DONE
        )
        ledger.add(c)
        assert not ledger.transition("c1", CommitmentStatus.OPEN, "2024-01-02T00:00:00+00:00")

    def test_overdue_list(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "d1", "2024-01-01T00:00:00+00:00"))
        ledger.add(Commitment("c2", "a", "b", "d2", "2024-12-01T00:00:00+00:00"))
        overdue = ledger.overdue("2024-06-01T00:00:00+00:00")
        assert len(overdue) == 1
        assert overdue[0].commitment_id == "c1"

    def test_by_status(self):
        ledger = CommitmentLedger()
        ledger.add(
            Commitment(
                "c1", "a", "b", "d1", "2024-01-01T00:00:00+00:00", status=CommitmentStatus.OPEN
            )
        )
        ledger.add(
            Commitment(
                "c2", "a", "b", "d2", "2024-01-01T00:00:00+00:00", status=CommitmentStatus.DONE
            )
        )
        assert len(ledger.by_status(CommitmentStatus.OPEN)) == 1
        assert len(ledger.by_status(CommitmentStatus.DONE)) == 1

    def test_upcoming(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "soon", "2024-01-05T00:00:00+00:00"))
        ledger.add(Commitment("c2", "a", "b", "far", "2024-06-01T00:00:00+00:00"))
        upcoming = ledger.upcoming("2024-01-01T00:00:00+00:00", days=7.0)
        assert len(upcoming) == 1
        assert upcoming[0].commitment_id == "c1"

    def test_transition_history(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00"))
        ledger.transition("c1", CommitmentStatus.IN_PROGRESS, "2024-01-02T00:00:00+00:00")
        ledger.transition("c1", CommitmentStatus.DONE, "2024-01-03T00:00:00+00:00")
        history = ledger.transition_history()
        assert len(history) >= 3  # created + 2 transitions
        actions = [h["action"] for h in history]
        assert "created" in actions
        assert "status_change" in actions

    def test_to_json(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "alice", "bob", "Report", "2024-03-01T00:00:00+00:00"))
        j = ledger.to_json()
        data = json.loads(j)
        assert "commitments" in data
        assert "history" in data
        assert len(data["commitments"]) == 1
        assert data["commitments"][0]["owed_by"] == "alice"

    def test_to_markdown(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "Deliver report", "2024-03-01T00:00:00+00:00"))
        md = ledger.to_markdown()
        assert "Commitment Ledger" in md
        assert "Deliver report" in md

    def test_by_owed_by_and_to(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "alice", "bob", "d1", "2024-01-01T00:00:00+00:00"))
        ledger.add(Commitment("c2", "bob", "alice", "d2", "2024-01-01T00:00:00+00:00"))
        assert len(ledger.by_owed_by("alice")) == 1
        assert len(ledger.by_owed_to("alice")) == 1


class TestGraceWindows:
    def test_per_commitment_grace_honored_by_default(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", grace_hours=6.0)
        assert not c.is_overdue("2024-01-01T03:00:00+00:00")
        assert c.is_overdue("2024-01-01T07:00:00+00:00")

    def test_explicit_grace_overrides_field(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", grace_hours=6.0)
        assert c.is_overdue("2024-01-01T03:00:00+00:00", grace_hours=0.0)

    def test_zero_grace_default_matches_previous_behavior(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00")
        assert not c.is_overdue("2024-01-01T00:00:00+00:00")
        assert c.is_overdue("2024-01-01T00:00:01+00:00")

    def test_ledger_overdue_uses_commitment_grace(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", grace_hours=48.0))
        assert ledger.overdue("2024-01-02T00:00:00+00:00") == []
        assert len(ledger.overdue("2024-01-04T00:00:00+00:00")) == 1


class TestNudges:
    def _ledger(self) -> CommitmentLedger:
        ledger = CommitmentLedger()
        ledger.add(Commitment("c_over", "alice", "bob", "ship report", "2024-01-01T00:00:00+00:00"))
        ledger.add(Commitment("c_soon", "carol", "dave", "review PR", "2024-01-10T12:00:00+00:00"))
        ledger.add(
            Commitment("c_far", "erin", "frank", "plan offsite", "2024-03-01T00:00:00+00:00")
        )
        ledger.add(
            Commitment(
                "c_done",
                "alice",
                "bob",
                "old task",
                "2024-01-05T00:00:00+00:00",
                status=CommitmentStatus.DONE,
            )
        )
        return ledger

    def test_overdue_and_upcoming_kinds(self):
        nudges = self._ledger().nudges("2024-01-09T12:00:00+00:00", ahead_days=2.0)
        by_id = {n.commitment_id: n for n in nudges}
        assert by_id["c_over"].kind == "overdue"
        assert by_id["c_soon"].kind == "upcoming"
        assert "c_far" not in by_id
        assert "c_done" not in by_id

    def test_nudges_sorted_by_due_then_id(self):
        nudges: list[Nudge] = self._ledger().nudges("2024-01-09T12:00:00+00:00")
        assert [n.commitment_id for n in nudges] == ["c_over", "c_soon"]

    def test_messages_cite_description_and_due(self):
        nudges = self._ledger().nudges("2024-01-09T12:00:00+00:00")
        over = next(n for n in nudges if n.commitment_id == "c_over")
        assert "ship report" in over.message
        assert over.due_date == "2024-01-01T00:00:00+00:00"
        assert over.owed_by == "alice"

    def test_grace_window_suppresses_nudge(self):
        ledger = CommitmentLedger()
        ledger.add(
            Commitment("g1", "a", "b", "task", "2024-01-01T00:00:00+00:00", grace_hours=72.0)
        )
        # inside grace: not overdue, and past-due items are never "upcoming"
        assert ledger.nudges("2024-01-02T00:00:00+00:00", ahead_days=2.0) == []

    def test_empty_ledger_no_nudges(self):
        assert CommitmentLedger().nudges("2024-01-09T12:00:00+00:00") == []
