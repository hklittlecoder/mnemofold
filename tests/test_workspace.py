"""Tests for the persistent workspace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.events import Event, EventType
from mnemofold.replay import TraceReader
from mnemofold.workspace import Workspace, WorkspaceStats, project_event

T0 = datetime(2025, 3, 10, 9, 0, tzinfo=UTC)


def _sample_events() -> list[Event]:
    return [
        Event.mail_received(
            T0,
            sender="alice",
            subject="kickoff",
            body="hello bob",
            recipients=["bob"],
            thread_id="t1",
        ),
        Event.note(T0 + timedelta(minutes=30), text="design thoughts", author="alice"),
        Event.document_change(
            T0 + timedelta(hours=2),
            doc_id="doc-alpha-1",
            title="spec",
            change_type="create",
            author="bob",
        ),
    ]


def _commitment_event() -> Event:
    return Event(
        EventType.MAIL_SENT,
        T0,
        {
            "persona_id": "alice",
            "subject": "Commitment: send the report",
            "body": "I owe you: send the report by 2025-03-20.",
            "commitment_ref": "c-1",
            "recipients": ["bob"],
        },
    )


class TestWorkspaceBasics:
    def test_open_creates_directory_and_files(self, tmp_path):
        with Workspace(tmp_path / "ws"):
            assert (tmp_path / "ws" / "journal.db").exists()
        assert (tmp_path / "ws" / "trace.jsonl").exists()

    def test_ingest_projects_memories(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            added = ws.ingest_events(_sample_events())
            assert added == 3
            stats = ws.stats()
            assert stats.events == 3
            assert stats.memories == 3
            assert stats.commitments == 0
            assert stats.tombstones == 0

    def test_reopen_rebuilds_same_digest(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_sample_events())
            digest = ws.stats().digest
        with Workspace(tmp_path / "ws") as reopened:
            assert reopened.stats().digest == digest
            assert reopened.stats().memories == 3

    def test_rebuild_twice_is_identical(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_sample_events())
            first = ws.rebuild()
            second = ws.rebuild()
            assert first.digest == second.digest

    def test_duplicate_ingest_is_idempotent(self, tmp_path):
        events = _sample_events()
        with Workspace(tmp_path / "ws") as ws:
            assert ws.ingest_events(events) == 3
            assert ws.ingest_events(events) == 0
            assert ws.stats().memories == 3

    def test_ledger_projects_planted_commitments(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events([_commitment_event()])
            assert ws.stats().commitments == 1
            commitment = ws.ledger.get("c-1")
            assert commitment is not None
            assert commitment.description == "send the report"
            assert commitment.due_date == "2025-03-20T00:00:00+00:00"
            assert commitment.owed_by == "alice"
            assert commitment.owed_to == "bob"

    def test_trace_records_ingest_and_verifies(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_sample_events())
        reader = TraceReader(tmp_path / "ws" / "trace.jsonl")
        assert reader.verify()
        assert reader.count() == 4  # three events + one ingest receipt

    def test_stats_shape(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_sample_events())
            stats = ws.stats()
            assert isinstance(stats, WorkspaceStats)
            assert len(stats.head_checksum) == 64
            assert len(stats.digest) == 64
            assert all(c in "0123456789abcdef" for c in stats.digest)

    def test_journal_chain_verifies(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_sample_events())
            assert ws.journal.verify_chain()


class TestProjectEvent:
    def test_projection_is_deterministic(self):
        event = _sample_events()[0]
        first = project_event(event)
        second = project_event(event)
        assert first.item_id == second.item_id == event.event_id
        assert first.title == "kickoff"
        assert first.content == second.content

    def test_title_falls_back_to_type(self):
        event = Event.focus_block(T0, duration_minutes=25, topic="deep work")
        item = project_event(event)
        assert item.title == "focus_block"
        assert "focus_block" in item.tags

    def test_created_at_matches_event_timestamp(self):
        event = _sample_events()[1]
        assert project_event(event).created_at == event.timestamp.isoformat()


class TestRebuildIdentity:
    def test_same_events_different_paths_same_digest(self, tmp_path):
        events = _sample_events() + [_commitment_event()]
        with Workspace(tmp_path / "a") as wa:
            wa.ingest_events(events)
        with Workspace(tmp_path / "b") as wb:
            wb.ingest_events(events)
        with Workspace(tmp_path / "a") as ra, Workspace(tmp_path / "b") as rb:
            assert ra.stats().digest == rb.stats().digest

    def test_digest_sensitive_to_content(self, tmp_path):
        with Workspace(tmp_path / "a") as wa:
            wa.ingest_events(_sample_events())
        altered = _sample_events()
        altered[1] = Event.note(
            T0 + timedelta(minutes=30), text="different thoughts", author="alice"
        )
        with Workspace(tmp_path / "b") as wb:
            wb.ingest_events(altered)
        with Workspace(tmp_path / "a") as ra, Workspace(tmp_path / "b") as rb:
            assert ra.stats().digest != rb.stats().digest

    def test_rebuild_return_matches_stats(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_sample_events())
            assert ws.rebuild().digest == ws.stats().digest

    def test_incremental_and_bulk_ingest_converge(self, tmp_path):
        events = _sample_events()
        with Workspace(tmp_path / "bulk") as ws:
            ws.ingest_events(events)
        with Workspace(tmp_path / "incr") as ws:
            for event in events:
                ws.ingest_events([event])
        with Workspace(tmp_path / "bulk") as a, Workspace(tmp_path / "incr") as b:
            assert a.stats().digest == b.stats().digest

    def test_ledger_reprojects_identically(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events([_commitment_event(), *_sample_events()])
            before = ws.ledger.to_json()
            ws.rebuild()
            assert ws.ledger.to_json() == before


class TestRememberForget:
    NOW = "2025-03-10T09:00:00+00:00"
    LATER = "2025-03-11T09:00:00+00:00"

    def test_remember_returns_content_addressed_id(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            item_id = ws.remember("buy milk", title="errand", now=self.NOW)
            assert item_id.startswith("evt_")
            item = ws.store.peek(item_id)
            assert item is not None
            assert "buy milk" in item.content

    def test_remember_same_instant_is_idempotent(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            first = ws.remember("buy milk", now=self.NOW)
            second = ws.remember("buy milk", now=self.NOW)
            assert first == second
            assert ws.stats().events == 1

    def test_remember_rejects_invalid_now(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws, pytest.raises(ValueError, match="invalid timestamp"):
            ws.remember("x", now="garbage")

    def test_remember_naive_now_read_as_utc(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            item_id = ws.remember("x", now="2025-03-10T09:00:00")
            assert ws.store.peek(item_id).created_at == "2025-03-10T09:00:00+00:00"

    def test_forget_removes_and_tombstones(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            item_id = ws.remember("secret note", now=self.NOW)
            report = ws.forget(item_id, reason="gdpr", now=self.LATER)
            assert report.total_deleted == 1
            assert ws.store.peek(item_id) is None
            assert ws.stats().tombstones == 1

    def test_forget_survives_reopen(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            item_id = ws.remember("secret note", now=self.NOW)
            ws.forget(item_id, now=self.LATER)
        with Workspace(tmp_path / "ws") as reopened:
            assert reopened.store.peek(item_id) is None
            assert reopened.stats().tombstones == 1
            # the journal keeps the frame and the chain still verifies
            assert len(reopened.journal) == 1
            assert reopened.journal.verify_chain()

    def test_reingest_of_forgotten_event_stays_forgotten(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            item_id = ws.remember("secret note", now=self.NOW)
            ws.forget(item_id, now=self.LATER)
            event = Event(
                EventType.NOTE,
                datetime(2025, 3, 10, 9, 0, tzinfo=UTC),
                {"text": "secret note", "title": "", "author": "user", "tags": []},
            )
            assert event.event_id == item_id
            ws.ingest_events([event])
            assert ws.store.peek(item_id) is None

    def test_forget_drops_ledger_commitment_from_that_event(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            event = _commitment_event()
            ws.ingest_events([event])
            assert ws.stats().commitments == 1
            ws.forget(event.event_id, now=self.LATER)
            assert ws.stats().commitments == 0

    def test_forget_unknown_item_reports_error(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws:
            report = ws.forget("evt_missing", now=self.LATER)
            assert report.total_deleted == 0
            assert report.errors

    def test_forget_invalid_now_raises(self, tmp_path):
        with Workspace(tmp_path / "ws") as ws, pytest.raises(ValueError, match="invalid timestamp"):
            ws.forget("evt_x", now="nope")
