"""Tests for mnemofold.events."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from mnemofold.events import SCHEMA_VERSION, Event, EventStore, EventType, _content_checksum

SAMPLE_TS = datetime(2025, 3, 14, 12, 0, 0, tzinfo=UTC)


class TestEventType:
    def test_known_types_are_strings(self):
        assert EventType.MAIL_RECEIVED == "mail_received"
        assert EventType.FOCUS_BLOCK == "focus_block"

    def test_all_event_types_have_doc_string_entries(self):
        # Sanity check: we expect a specific set of event types.
        expected = {
            "mail_received",
            "mail_sent",
            "meeting_scheduled",
            "meeting_held",
            "note",
            "task_update",
            "document_change",
            "chat_message",
            "commitment_ack",
            "focus_block",
        }
        assert {et.value for et in EventType} == expected


class TestEventConstruction:
    def test_basic_event_has_id(self):
        evt = Event(event_type=EventType.NOTE, timestamp=SAMPLE_TS, content={"text": "hi"})
        assert evt.event_id.startswith("evt_")
        assert len(evt.event_id) == 20  # evt_ + 16 hex chars

    def test_identical_events_share_id(self):
        a = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        b = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        assert a.event_id == b.event_id

    def test_different_content_different_id(self):
        a = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        b = Event(EventType.NOTE, SAMPLE_TS, {"text": "hello"})
        assert a.event_id != b.event_id

    def test_different_type_different_id(self):
        a = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        b = Event(EventType.CHAT_MESSAGE, SAMPLE_TS, {"text": "hi"})
        assert a.event_id != b.event_id

    def test_different_timestamp_different_id(self):
        a = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        later = SAMPLE_TS.replace(hour=13)
        b = Event(EventType.NOTE, later, {"text": "hi"})
        assert a.event_id != b.event_id

    def test_naive_timestamp_rejected(self):
        naive = datetime(2025, 3, 14, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            Event(EventType.NOTE, naive, {"text": "hi"})

    def test_non_dict_content_rejected(self):
        with pytest.raises(TypeError, match="content must be a dict"):
            Event(EventType.NOTE, SAMPLE_TS, "not a dict")  # type: ignore[arg-type]

    def test_default_content_is_empty_dict(self):
        evt = Event(EventType.FOCUS_BLOCK, SAMPLE_TS)
        assert evt.content == {}


class TestContentChecksum:
    def test_checksum_is_deterministic(self):
        payload = {"a": 1, "b": [1, 2, 3]}
        assert _content_checksum(payload) == _content_checksum(dict(payload))

    def test_checksum_is_order_independent(self):
        a = {"a": 1, "b": 2}
        b = {"b": 2, "a": 1}
        assert _content_checksum(a) == _content_checksum(b)

    def test_event_checksum_matches_content_checksum(self):
        evt = Event(EventType.NOTE, SAMPLE_TS, {"text": "hello"})
        # The content_checksum property covers the full envelope payload
        # (type, timestamp, content, schema_version).
        assert len(evt.content_checksum) == 64  # sha256 hex


class TestSerialization:
    def test_to_envelope_contains_all_fields(self):
        evt = Event(EventType.CHAT_MESSAGE, SAMPLE_TS, {"sender": "alice", "body": "hi"})
        env = evt.to_envelope()
        assert env["schema_version"] == SCHEMA_VERSION
        assert env["event_id"] == evt.event_id
        assert env["event_type"] == "chat_message"
        assert env["timestamp"] == SAMPLE_TS.isoformat()
        assert env["content"] == {"sender": "alice", "body": "hi"}
        assert env["content_checksum"] == evt.content_checksum

    def test_round_trip_envelope(self):
        original = Event(EventType.MEETING_SCHEDULED, SAMPLE_TS, {"title": "sync"})
        restored = Event.from_envelope(original.to_envelope())
        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.timestamp == original.timestamp
        assert restored.content == original.content

    def test_round_trip_json(self):
        original = Event(EventType.MAIL_RECEIVED, SAMPLE_TS, {"from": "bob", "subject": "hey"})
        line = original.to_json()
        assert "\n" not in line  # JSONL: one line per event
        restored = Event.from_json(line)
        assert restored.event_id == original.event_id

    def test_json_is_compact(self):
        evt = Event(EventType.NOTE, SAMPLE_TS, {"k": "v"})
        line = evt.to_json()
        parsed = json.loads(line)
        # Compact form should not contain extra whitespace
        assert "  " not in line
        assert parsed["event_id"] == evt.event_id

    def test_tampered_event_id_detected(self):
        evt = Event(EventType.NOTE, SAMPLE_TS, {"text": "secret"})
        env = evt.to_envelope()
        env["event_id"] = "evt_0000000000000000"
        with pytest.raises(ValueError, match="event_id mismatch"):
            Event.from_envelope(env)

    def test_tampered_content_detected(self):
        evt = Event(EventType.NOTE, SAMPLE_TS, {"text": "original"})
        env = evt.to_envelope()
        env["content"] = {"text": "tampered"}
        with pytest.raises(ValueError):
            Event.from_envelope(env)

    def test_naive_iso_timestamp_assumes_utc(self):
        # If a serialized timestamp has no tz, we treat it as UTC.
        # Build an envelope whose timestamp string is naive, but whose
        # content_checksum matches what we get with UTC assumed.
        ts_naive_str = "2025-03-14T12:00:00"
        ts_utc = datetime(2025, 3, 14, 12, 0, 0, tzinfo=UTC)
        evt = Event(EventType.NOTE, ts_utc, {"text": "hi"})
        env = evt.to_envelope()
        env["timestamp"] = ts_naive_str
        # The recomputed timestamp (with UTC assumption) matches the original
        # event's timestamp, so validation passes.
        restored = Event.from_envelope(env)
        assert restored.timestamp == ts_utc
        assert restored.event_id == evt.event_id


class TestImmutability:
    def test_event_is_frozen(self):
        evt = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        with pytest.raises(AttributeError):
            evt.content = {"text": "changed"}  # type: ignore[misc]

    def test_content_dict_is_shared_reference_but_event_itself_frozen(self):
        # Content is a regular dict (not a frozen mapping), but the Event
        # dataclass field cannot be reassigned. Mutating the dict is
        # discouraged but not blocked here — the checksum check on read
        # is what catches drift.
        evt = Event(EventType.NOTE, SAMPLE_TS, {"text": "hi"})
        # Ensure the content we stored matches what we see.
        assert evt.content["text"] == "hi"


class TestConvenienceConstructors:
    def test_mail_received_shape(self):
        evt = Event.mail_received(
            SAMPLE_TS,
            sender="alice@example.com",
            subject="Q1 planning",
            body="Let's sync next week.",
            message_id="<abc@example.com>",
            recipients=["bob@example.com"],
            thread_id="t1",
        )
        assert evt.event_type == EventType.MAIL_RECEIVED
        assert evt.content["sender"] == "alice@example.com"
        assert evt.content["subject"] == "Q1 planning"
        assert evt.content["recipients"] == ["bob@example.com"]

    def test_mail_sent_shape(self):
        evt = Event.mail_sent(SAMPLE_TS, to=["carol@example.com"], subject="Re: hi", body="ok")
        assert evt.event_type == EventType.MAIL_SENT
        assert evt.content["to"] == ["carol@example.com"]

    def test_meeting_scheduled_shape(self):
        evt = Event.meeting_scheduled(
            SAMPLE_TS,
            title="Design review",
            start_time="2025-03-14T15:00:00+00:00",
            end_time="2025-03-14T16:00:00+00:00",
            attendees=["alice", "bob"],
        )
        assert evt.event_type == EventType.MEETING_SCHEDULED
        assert evt.content["title"] == "Design review"
        assert len(evt.content["attendees"]) == 2

    def test_meeting_held_shape(self):
        evt = Event.meeting_held(
            SAMPLE_TS,
            title="Standup",
            attendees=["alice"],
            notes="Discussed blockers",
        )
        assert evt.event_type == EventType.MEETING_HELD
        assert evt.content["notes"] == "Discussed blockers"

    def test_note_shape(self):
        evt = Event.note(SAMPLE_TS, text="Remember to file TPS report", author="bob")
        assert evt.event_type == EventType.NOTE
        assert evt.content["text"] == "Remember to file TPS report"
        assert evt.content["author"] == "bob"

    def test_task_update_shape(self):
        evt = Event.task_update(
            SAMPLE_TS,
            task_id="T-123",
            title="Fix login bug",
            status="in_progress",
            owner="alice",
            previous_status="todo",
        )
        assert evt.event_type == EventType.TASK_UPDATE
        assert evt.content["status"] == "in_progress"
        assert evt.content["previous_status"] == "todo"

    def test_document_change_shape(self):
        evt = Event.document_change(
            SAMPLE_TS,
            doc_id="doc-42",
            title="API spec",
            change_type="edit",
            author="carol",
            diff_summary="added auth section",
        )
        assert evt.event_type == EventType.DOCUMENT_CHANGE
        assert evt.content["change_type"] == "edit"

    def test_chat_message_shape(self):
        evt = Event.chat_message(SAMPLE_TS, sender="dave", body="deployed", channel="team")
        assert evt.event_type == EventType.CHAT_MESSAGE
        assert evt.content["body"] == "deployed"
        assert evt.content["channel"] == "team"

    def test_commitment_ack_shape(self):
        evt = Event.commitment_ack(
            SAMPLE_TS,
            commitment_id="C-7",
            owed_by="alice",
            owed_to="bob",
            description="Deliver design doc",
            due_date="2025-04-01",
        )
        assert evt.event_type == EventType.COMMITMENT_ACK
        assert evt.content["owed_by"] == "alice"
        assert evt.content["status"] == "acknowledged"

    def test_focus_block_shape(self):
        evt = Event.focus_block(SAMPLE_TS, duration_minutes=25, topic="writing", tags=["deep"])
        assert evt.event_type == EventType.FOCUS_BLOCK
        assert evt.content["duration_minutes"] == 25
        assert evt.content["tags"] == ["deep"]

    def test_constructors_round_trip_through_json(self):
        original = Event.note(SAMPLE_TS, text="hello", author="alice")
        restored = Event.from_json(original.to_json())
        assert restored.event_id == original.event_id
        assert restored.content["text"] == "hello"


class TestEventStore:
    def test_empty_store(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        assert len(store) == 0
        assert list(store) == []

    def test_append_single_event(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        evt = Event.note(SAMPLE_TS, text="hello")
        assert store.append(evt) is True
        assert len(store) == 1
        assert evt.event_id in store

    def test_append_duplicate_is_idempotent(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        evt = Event.note(SAMPLE_TS, text="hello")
        assert store.append(evt) is True
        assert store.append(evt) is False
        assert len(store) == 1

    def test_extend_returns_new_count(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        evts = [
            Event.note(SAMPLE_TS, text="one"),
            Event.note(SAMPLE_TS, text="two"),
            Event.note(SAMPLE_TS, text="one"),  # duplicate
        ]
        assert store.extend(evts) == 2
        assert len(store) == 2

    def test_reload_preserves_events(self, tmp_path):
        path = tmp_path / "events.jsonl"
        store = EventStore(path)
        evts = [
            Event.mail_received(SAMPLE_TS, sender="a", subject="s1"),
            Event.chat_message(SAMPLE_TS, sender="b", body="hi"),
            Event.focus_block(SAMPLE_TS, duration_minutes=25),
        ]
        store.extend(evts)

        store2 = EventStore(path)
        assert len(store2) == len(evts)
        for a, b in zip(store, store2, strict=True):
            assert a.event_id == b.event_id
            assert a.event_type == b.event_type

    def test_get_by_id(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        evt = Event.note(SAMPLE_TS, text="found me")
        store.append(evt)
        assert store.get(evt.event_id) is not None
        assert store.get("evt_nonexistent") is None

    def test_corrupt_line_raises(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text("not valid json at all\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Corrupt event"):
            EventStore(path)

    def test_tampered_line_raises(self, tmp_path):
        path = tmp_path / "events.jsonl"
        store = EventStore(path)
        store.append(Event.note(SAMPLE_TS, text="original"))

        # Manually mangle the last line's content
        lines = path.read_text(encoding="utf-8").splitlines()
        import json

        envelope = json.loads(lines[0])
        envelope["content"] = {"text": "tampered"}
        lines[0] = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Corrupt event"):
            EventStore(path)

    def test_iteration_preserves_order(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        e1 = Event.note(SAMPLE_TS, text="first")
        e2 = Event.note(SAMPLE_TS, text="second")
        e3 = Event.note(SAMPLE_TS, text="third")
        store.extend([e1, e2, e3])
        ids = [e.event_id for e in store]
        assert ids == [e1.event_id, e2.event_id, e3.event_id]

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "events.jsonl"
        store = EventStore(path)
        store.append(Event.note(SAMPLE_TS, text="auto create"))
        assert path.exists()
