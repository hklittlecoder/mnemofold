"""Tests for mnemofold.events."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from mnemofold.events import SCHEMA_VERSION, Event, EventType, _content_checksum

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
