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


class TestLedgerJsonRoundtrip:
    def _ledger(self) -> CommitmentLedger:
        ledger = CommitmentLedger()
        ledger.add(
            Commitment(
                "c1",
                "alice",
                "bob",
                "ship parser",
                "2024-02-01T00:00:00+00:00",
                priority=0.8,
                created_at="2024-01-01T00:00:00+00:00",
                tags={"alpha"},
                grace_hours=12.0,
                source_event_ids=["evt_1"],
                depends_on=["c0"],
                metadata={"project": "alpha"},
            )
        )
        ledger.add(Commitment("c2", "carol", "dave", "review design", "2024-02-10T00:00:00+00:00"))
        ledger.transition("c2", CommitmentStatus.IN_PROGRESS, "2024-01-15T00:00:00+00:00")
        return ledger

    def test_export_import_export_is_stable(self):
        original = self._ledger()
        restored = CommitmentLedger.from_json(original.to_json())
        assert restored.to_json() == original.to_json()

    def test_roundtrip_preserves_every_field(self):
        restored = CommitmentLedger.from_json(self._ledger().to_json())
        c1 = restored.get("c1")
        assert c1 is not None
        assert c1.owed_by == "alice"
        assert c1.owed_to == "bob"
        assert c1.priority == 0.8
        assert c1.grace_hours == 12.0
        assert c1.tags == {"alpha"}
        assert c1.source_event_ids == ["evt_1"]
        assert c1.depends_on == ["c0"]
        assert c1.metadata == {"project": "alpha"}
        c2 = restored.get("c2")
        assert c2 is not None
        assert c2.status == CommitmentStatus.IN_PROGRESS

    def test_history_restored_without_duplicates(self):
        original = self._ledger()
        restored = CommitmentLedger.from_json(original.to_json())
        assert restored.transition_history() == original.transition_history()

    def test_empty_ledger_roundtrip(self):
        empty = CommitmentLedger()
        restored = CommitmentLedger.from_json(empty.to_json())
        assert restored.total_count() == 0
        assert restored.transition_history() == []

    def test_unknown_status_is_rejected(self):
        payload = json.loads(self._ledger().to_json())
        payload["commitments"][0]["status"] = "exploded"
        with pytest.raises(ValueError):
            CommitmentLedger.from_json(json.dumps(payload))

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            CommitmentLedger.from_json("{not json")


class TestBlockedDependencies:
    def _ledger(self) -> CommitmentLedger:
        ledger = CommitmentLedger()
        ledger.add(Commitment("dep1", "alice", "bob", "draft spec", "2024-01-20T00:00:00+00:00"))
        ledger.add(
            Commitment(
                "main",
                "carol",
                "dave",
                "build feature",
                "2024-01-25T00:00:00+00:00",
                depends_on=["dep1", "missing"],
            )
        )
        return ledger

    def test_open_dependencies_lists_unfinished_in_order(self):
        ledger = self._ledger()
        assert ledger.open_dependencies("main") == ["dep1", "missing"]
        ledger.transition("dep1", CommitmentStatus.DONE, "2024-01-19T00:00:00+00:00")
        # unknown dependency ids stay blocking (conservative)
        assert ledger.open_dependencies("main") == ["missing"]

    def test_no_dependencies_no_blocking(self):
        assert self._ledger().open_dependencies("dep1") == []

    def test_unknown_commitment_has_no_dependencies(self):
        assert self._ledger().open_dependencies("nope") == []

    def test_blocked_commitments_listing(self):
        ledger = self._ledger()
        assert [c.commitment_id for c in ledger.blocked_commitments()] == ["main"]
        ledger.transition("main", CommitmentStatus.DONE, "2024-01-24T00:00:00+00:00")
        assert ledger.blocked_commitments() == []

    def test_blocked_nudge_kind_and_message(self):
        ledger = self._ledger()
        nudges = ledger.nudges("2024-01-24T00:00:00+00:00", ahead_days=2.0)
        by_id = {n.commitment_id: n for n in nudges}
        assert by_id["dep1"].kind == "overdue"
        assert by_id["main"].kind == "blocked"
        assert "dep1" in by_id["main"].message
        assert "missing" in by_id["main"].message

    def test_overdue_nudge_mentions_blockers(self):
        ledger = self._ledger()
        nudges = ledger.nudges("2024-01-26T00:00:00+00:00")
        main = next(n for n in nudges if n.commitment_id == "main")
        assert main.kind == "overdue"
        assert "blocked by dep1, missing" in main.message

    def test_far_blocked_commitment_not_nudged(self):
        ledger = CommitmentLedger()
        ledger.add(
            Commitment(
                "later",
                "a",
                "b",
                "far task",
                "2024-06-01T00:00:00+00:00",
                depends_on=["missing"],
            )
        )
        assert ledger.nudges("2024-01-24T00:00:00+00:00", ahead_days=2.0) == []


class TestTransitionMatrix:
    ALL = list(CommitmentStatus)
    TS = "2024-01-02T00:00:00+00:00"

    def _ledger_with(self, status: CommitmentStatus) -> CommitmentLedger:
        ledger = CommitmentLedger()
        ledger.add(Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00", status=status))
        return ledger

    def test_every_pair_matches_transition_table(self):
        for start in self.ALL:
            for target in self.ALL:
                ledger = self._ledger_with(start)
                expected = target in VALID_TRANSITIONS[start]
                result = ledger.transition("c1", target, self.TS)
                assert result is expected, f"{start} -> {target}"
                assert ledger.get("c1").status == (target if expected else start)

    def test_terminal_states_have_no_exits(self):
        for terminal in (
            CommitmentStatus.DONE,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.SUPERSEDED,
        ):
            assert VALID_TRANSITIONS[terminal] == set()

    def test_failed_transition_leaves_timestamps_untouched(self):
        ledger = self._ledger_with(CommitmentStatus.DONE)
        assert ledger.transition("c1", CommitmentStatus.OPEN, self.TS) is False
        assert ledger.get("c1").updated_at != self.TS

    def test_history_records_only_successful_transitions(self):
        ledger = self._ledger_with(CommitmentStatus.OPEN)
        ledger.transition("c1", CommitmentStatus.DONE, self.TS)
        ledger.transition("c1", CommitmentStatus.OPEN, "2024-01-03T00:00:00+00:00")
        history = ledger.transition_history()
        assert len(history) == 2  # created + one successful change
        assert history[-1] == {
            "commitment_id": "c1",
            "action": "status_change",
            "from_status": "open",
            "to_status": "done",
            "timestamp": self.TS,
        }

    def test_unknown_commitment_transition_fails(self):
        ledger = CommitmentLedger()
        assert ledger.transition("nope", CommitmentStatus.DONE, self.TS) is False

    def test_string_status_argument_accepted(self):
        ledger = self._ledger_with(CommitmentStatus.OPEN)
        assert ledger.transition("c1", "done", self.TS) is True
        assert ledger.get("c1").status == CommitmentStatus.DONE

    def test_markdown_export_is_stable_and_ordered(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("b", "x", "y", "second task", "2024-02-01T00:00:00+00:00"))
        ledger.add(Commitment("a", "x", "y", "first task", "2024-01-01T00:00:00+00:00"))
        first = ledger.to_markdown()
        assert first == ledger.to_markdown()
        assert first.index("first task") < first.index("second task")

    def test_by_status_accepts_string(self):
        ledger = self._ledger_with(CommitmentStatus.OPEN)
        assert len(ledger.by_status("open")) == 1
        assert ledger.by_status("done") == []


class TestLedgerEdges:
    def test_days_until_due_negative_and_invalid(self):
        c = Commitment("c1", "a", "b", "d", "2024-01-01T00:00:00+00:00")
        assert c.days_until_due("2024-01-11T00:00:00+00:00") == -10.0
        assert c.days_until_due("garbage") is None
        bad = Commitment("c2", "a", "b", "d", "not-a-date")
        assert bad.days_until_due("2024-01-01T00:00:00+00:00") is None
        assert bad.is_overdue("2024-01-01T00:00:00+00:00") is False

    def test_upcoming_includes_past_due_and_window_edge(self):
        ledger = CommitmentLedger()
        ledger.add(Commitment("past", "a", "b", "d", "2024-01-01T00:00:00+00:00"))
        ledger.add(Commitment("edge", "a", "b", "d", "2024-01-08T00:00:00+00:00"))
        ledger.add(Commitment("outside", "a", "b", "d", "2024-02-01T00:00:00+00:00"))
        ids = [c.commitment_id for c in ledger.upcoming("2024-01-01T00:00:00+00:00", days=7.0)]
        assert ids == ["past", "edge"]

    def test_upcoming_skips_closed_statuses(self):
        ledger = CommitmentLedger()
        ledger.add(
            Commitment(
                "done",
                "a",
                "b",
                "d",
                "2024-01-02T00:00:00+00:00",
                status=CommitmentStatus.DONE,
            )
        )
        assert ledger.upcoming("2024-01-01T00:00:00+00:00") == []

    def test_mixed_offset_due_dates_compare_as_instants(self):
        ledger = CommitmentLedger()
        # due 2024-01-01T20:00-08:00 == 2024-01-02T04:00Z: overdue at 05:00Z
        ledger.add(Commitment("tz", "a", "b", "d", "2024-01-01T20:00:00-08:00"))
        assert len(ledger.overdue("2024-01-02T05:00:00+00:00")) == 1
        assert ledger.overdue("2024-01-02T03:00:00+00:00") == []
