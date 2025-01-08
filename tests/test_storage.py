"""Tests for mnemofold.storage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mnemofold.events import Event
from mnemofold.storage import Journal, _frame_chain_checksum, _genesis_chain_checksum

SAMPLE_TS = datetime(2025, 3, 14, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def empty_journal(tmp_path):
    j = Journal(tmp_path / "test.db")
    yield j
    j.close()


@pytest.fixture
def sample_events():
    return [
        Event.note(SAMPLE_TS, text="first note"),
        Event.chat_message(SAMPLE_TS, sender="alice", body="hello"),
        Event.mail_received(SAMPLE_TS, sender="bob@example.com", subject="hi"),
        Event.focus_block(SAMPLE_TS, duration_minutes=25),
        Event.note(SAMPLE_TS, text="second note"),
    ]


class TestJournalConstruction:
    def test_creates_db_file(self, tmp_path):
        db = tmp_path / "journal.db"
        assert not db.exists()
        j = Journal(db)
        assert db.exists()
        j.close()

    def test_creates_parent_dirs(self, tmp_path):
        db = tmp_path / "a" / "b" / "journal.db"
        j = Journal(db)
        assert db.exists()
        j.close()

    def test_context_manager(self, tmp_path):
        db = tmp_path / "journal.db"
        with Journal(db) as j:
            assert len(j) == 0
        # After exit, connection is closed — operations would fail
        # (we just test that no error was raised)

    def test_schema_version_recorded(self, empty_journal):
        cur = empty_journal._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        )
        assert cur.fetchone() is not None


class TestJournalAppend:
    def test_append_single_event(self, empty_journal):
        evt = Event.note(SAMPLE_TS, text="hello")
        assert empty_journal.append(evt) is True
        assert len(empty_journal) == 1
        assert evt.event_id in empty_journal

    def test_append_duplicate_is_idempotent(self, empty_journal):
        evt = Event.note(SAMPLE_TS, text="hello")
        assert empty_journal.append(evt) is True
        assert empty_journal.append(evt) is False
        assert len(empty_journal) == 1

    def test_extend(self, empty_journal, sample_events):
        count = empty_journal.extend(sample_events)
        assert count == len(sample_events)
        assert len(empty_journal) == len(sample_events)

    def test_extend_with_duplicates(self, empty_journal):
        evts = [
            Event.note(SAMPLE_TS, text="a"),
            Event.note(SAMPLE_TS, text="a"),  # duplicate
            Event.note(SAMPLE_TS, text="b"),
        ]
        count = empty_journal.extend(evts)
        assert count == 2
        assert len(empty_journal) == 2


class TestJournalRead:
    def test_get_existing(self, empty_journal):
        evt = Event.note(SAMPLE_TS, text="find me")
        empty_journal.append(evt)
        got = empty_journal.get(evt.event_id)
        assert got is not None
        assert got.event_id == evt.event_id
        assert got.content["text"] == "find me"

    def test_get_missing(self, empty_journal):
        assert empty_journal.get("evt_nonexistent") is None

    def test_iter_forward(self, empty_journal, sample_events):
        empty_journal.extend(sample_events)
        ids = [e.event_id for e in empty_journal]
        expected = [e.event_id for e in sample_events]
        assert ids == expected

    def test_iter_reverse(self, empty_journal, sample_events):
        empty_journal.extend(sample_events)
        ids = [e.event_id for e in empty_journal.iter_events(reverse=True)]
        expected = [e.event_id for e in reversed(sample_events)]
        assert ids == expected

    def test_contains(self, empty_journal):
        evt = Event.note(SAMPLE_TS, text="x")
        empty_journal.append(evt)
        assert evt.event_id in empty_journal
        assert "evt_other" not in empty_journal

    def test_last_seq(self, empty_journal, sample_events):
        assert empty_journal.last_seq() == 0
        empty_journal.extend(sample_events)
        assert empty_journal.last_seq() == len(sample_events)


class TestFrameInfo:
    def test_frame_info(self, empty_journal):
        evt = Event.note(SAMPLE_TS, text="info")
        empty_journal.append(evt)
        info = empty_journal.frame_info(1)
        assert info is not None
        assert info.seq == 1
        assert info.event_id == evt.event_id
        assert info.event_type == "note"
        assert info.timestamp == SAMPLE_TS

    def test_frame_info_missing(self, empty_journal):
        assert empty_journal.frame_info(999) is None


class TestHashChain:
    def test_verify_chain_empty(self, empty_journal):
        assert empty_journal.verify_chain() is True

    def test_verify_chain_with_events(self, empty_journal, sample_events):
        empty_journal.extend(sample_events)
        assert empty_journal.verify_chain() is True

    def test_chain_starts_from_genesis(self, empty_journal):
        # First frame's prev_chain should equal genesis
        evt = Event.note(SAMPLE_TS, text="first")
        empty_journal.append(evt)
        info = empty_journal.frame_info(1)
        assert info is not None
        assert info.prev_chain_checksum == _genesis_chain_checksum()

    def test_chain_links_frames(self, empty_journal):
        evts = [
            Event.note(SAMPLE_TS, text="a"),
            Event.note(SAMPLE_TS, text="b"),
        ]
        empty_journal.extend(evts)
        info1 = empty_journal.frame_info(1)
        info2 = empty_journal.frame_info(2)
        assert info1 is not None and info2 is not None
        assert info2.prev_chain_checksum == info1.chain_checksum

    def test_chain_computation_is_manual(self, empty_journal):
        evt = Event.note(SAMPLE_TS, text="manual")
        empty_journal.append(evt)
        info = empty_journal.frame_info(1)
        assert info is not None
        expected = _frame_chain_checksum(_genesis_chain_checksum(), evt.to_json())
        assert info.chain_checksum == expected

    def test_head_checksum_empty(self, empty_journal):
        assert empty_journal.head_checksum() == _genesis_chain_checksum()

    def test_head_checksum_matches_last_frame(self, empty_journal, sample_events):
        empty_journal.extend(sample_events)
        last_seq = empty_journal.last_seq()
        last_info = empty_journal.frame_info(last_seq)
        assert last_info is not None
        assert empty_journal.head_checksum() == last_info.chain_checksum

    def test_tampering_breaks_chain(self, tmp_path):
        db = tmp_path / "tamper.db"
        j = Journal(db)
        evts = [
            Event.note(SAMPLE_TS, text="original"),
            Event.note(SAMPLE_TS, text="second"),
        ]
        j.extend(evts)
        assert j.verify_chain() is True
        j.close()

        # Directly mangle the first frame's envelope
        import sqlite3

        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE frames SET envelope_json = ? WHERE seq = 1",
            ('{"tampered": true}',),
        )
        conn.commit()
        conn.close()

        j2 = Journal(db)
        assert j2.verify_chain() is False
        j2.close()


class TestJournalReopen:
    def test_reopen_preserves_frames(self, tmp_path, sample_events):
        db = tmp_path / "reopen.db"
        j = Journal(db)
        j.extend(sample_events)
        head = j.head_checksum()
        n = len(j)
        j.close()

        j2 = Journal(db)
        assert len(j2) == n
        assert j2.head_checksum() == head
        # Verify forward iteration order matches
        for a, b in zip(sample_events, j2, strict=True):
            assert a.event_id == b.event_id
        j2.close()

    def test_append_after_reopen_continues_chain(self, tmp_path):
        db = tmp_path / "reopen2.db"
        j = Journal(db)
        j.append(Event.note(SAMPLE_TS, text="first"))
        head_before = j.head_checksum()
        j.close()

        j2 = Journal(db)
        j2.append(Event.note(SAMPLE_TS, text="second"))
        info2 = j2.frame_info(2)
        assert info2 is not None
        assert info2.prev_chain_checksum == head_before
        assert j2.verify_chain()
        j2.close()


class TestSchemaVersionGuard:
    def test_newer_schema_rejected(self, tmp_path):
        db = tmp_path / "newer.db"
        # Create a journal and manually bump the schema version
        j = Journal(db)
        j.close()
        import sqlite3

        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
            ("999",),
        )
        conn.commit()
        conn.close()

        with pytest.raises(RuntimeError, match="newer than code version"):
            Journal(db)
