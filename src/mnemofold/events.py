"""Typed event definitions for mnemofold.

Events are the atomic unit of memory. Each event has a deterministic
content-addressed ID derived from its payload, and a schema-versioned
envelope so older events can still be read by newer code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1


class EventType(StrEnum):
    """All event types understood by the memory system."""

    MAIL_RECEIVED = "mail_received"
    MAIL_SENT = "mail_sent"
    MEETING_SCHEDULED = "meeting_scheduled"
    MEETING_HELD = "meeting_held"
    NOTE = "note"
    TASK_UPDATE = "task_update"
    DOCUMENT_CHANGE = "document_change"
    CHAT_MESSAGE = "chat_message"
    COMMITMENT_ACK = "commitment_ack"
    FOCUS_BLOCK = "focus_block"


def _content_checksum(payload: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 hex digest of a payload dict.

    Keys are sorted so equivalent payloads produce the same checksum
    regardless of insertion order.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Event:
    """An immutable, content-addressed event.

    The ``event_id`` is derived deterministically from the event type,
    timestamp, and content payload.  Two events constructed with identical
    fields always have the same ``event_id``.
    """

    event_type: EventType
    timestamp: datetime
    content: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise TypeError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if not isinstance(self.content, dict):
            raise TypeError("content must be a dict")
        # Build the canonical payload used for id / checksum computation.
        # We compute the checksum from normalized fields, then inject event_id
        # via object.__setattr__ because the dataclass is frozen.
        payload = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "schema_version": self.schema_version,
        }
        checksum = _content_checksum(payload)
        object.__setattr__(self, "event_id", f"evt_{checksum[:16]}")

    @property
    def content_checksum(self) -> str:
        """Full SHA-256 hex digest of the canonical content payload."""
        payload = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "schema_version": self.schema_version,
        }
        return _content_checksum(payload)

    def to_envelope(self) -> dict[str, Any]:
        """Serialize to a schema-versioned envelope dict."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "content": dict(self.content),
            "content_checksum": self.content_checksum,
        }

    def to_json(self) -> str:
        """Serialize to a compact JSON string (one line, for JSONL)."""
        return json.dumps(
            self.to_envelope(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> Event:
        """Reconstruct an Event from a previously serialized envelope.

        Validates that the stored ``event_id`` and ``content_checksum`` match
        what we derive from the payload, so tampering is detected.
        """
        sv = envelope.get("schema_version", 1)
        if sv != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version: {sv}")
        event_type = EventType(envelope["event_type"])
        timestamp = datetime.fromisoformat(envelope["timestamp"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        content = dict(envelope["content"])
        event = cls(event_type=event_type, timestamp=timestamp, content=content, schema_version=sv)
        # Verify integrity
        if event.event_id != envelope["event_id"]:
            raise ValueError(
                f"event_id mismatch: expected {envelope['event_id']}, got {event.event_id}"
            )
        if event.content_checksum != envelope.get("content_checksum"):
            raise ValueError("content_checksum does not match payload")
        return event

    @classmethod
    def from_json(cls, line: str) -> Event:
        """Parse a single JSON line into an Event."""
        return cls.from_envelope(json.loads(line))

    # ------------------------------------------------------------------
    # Convenience constructors for each event type.
    #
    # These give typed callers a clear shape for each event's content
    # without requiring a separate dataclass per type.
    # ------------------------------------------------------------------

    @classmethod
    def mail_received(
        cls,
        timestamp: datetime,
        *,
        sender: str,
        subject: str,
        body: str = "",
        message_id: str = "",
        recipients: list[str] | None = None,
        thread_id: str = "",
    ) -> Event:
        content = {
            "sender": sender,
            "subject": subject,
            "body": body,
            "message_id": message_id,
            "recipients": recipients or [],
            "thread_id": thread_id,
        }
        return cls(EventType.MAIL_RECEIVED, timestamp, content)

    @classmethod
    def mail_sent(
        cls,
        timestamp: datetime,
        *,
        to: list[str],
        subject: str,
        body: str = "",
        message_id: str = "",
        thread_id: str = "",
    ) -> Event:
        content = {
            "to": to,
            "subject": subject,
            "body": body,
            "message_id": message_id,
            "thread_id": thread_id,
        }
        return cls(EventType.MAIL_SENT, timestamp, content)

    @classmethod
    def meeting_scheduled(
        cls,
        timestamp: datetime,
        *,
        title: str,
        start_time: str,
        end_time: str,
        attendees: list[str] | None = None,
        location: str = "",
        meeting_id: str = "",
    ) -> Event:
        content = {
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "attendees": attendees or [],
            "location": location,
            "meeting_id": meeting_id,
        }
        return cls(EventType.MEETING_SCHEDULED, timestamp, content)

    @classmethod
    def meeting_held(
        cls,
        timestamp: datetime,
        *,
        title: str,
        attendees: list[str] | None = None,
        notes: str = "",
        meeting_id: str = "",
    ) -> Event:
        content = {
            "title": title,
            "attendees": attendees or [],
            "notes": notes,
            "meeting_id": meeting_id,
        }
        return cls(EventType.MEETING_HELD, timestamp, content)

    @classmethod
    def note(cls, timestamp: datetime, *, text: str, author: str = "", note_id: str = "") -> Event:
        content = {"text": text, "author": author, "note_id": note_id}
        return cls(EventType.NOTE, timestamp, content)

    @classmethod
    def task_update(
        cls,
        timestamp: datetime,
        *,
        task_id: str,
        title: str,
        status: str,
        owner: str = "",
        due_date: str = "",
        previous_status: str = "",
    ) -> Event:
        content = {
            "task_id": task_id,
            "title": title,
            "status": status,
            "owner": owner,
            "due_date": due_date,
            "previous_status": previous_status,
        }
        return cls(EventType.TASK_UPDATE, timestamp, content)

    @classmethod
    def document_change(
        cls,
        timestamp: datetime,
        *,
        doc_id: str,
        title: str,
        change_type: str,
        author: str = "",
        diff_summary: str = "",
    ) -> Event:
        content = {
            "doc_id": doc_id,
            "title": title,
            "change_type": change_type,
            "author": author,
            "diff_summary": diff_summary,
        }
        return cls(EventType.DOCUMENT_CHANGE, timestamp, content)

    @classmethod
    def chat_message(
        cls,
        timestamp: datetime,
        *,
        sender: str,
        body: str,
        channel: str = "",
        thread_id: str = "",
        message_id: str = "",
    ) -> Event:
        content = {
            "sender": sender,
            "body": body,
            "channel": channel,
            "thread_id": thread_id,
            "message_id": message_id,
        }
        return cls(EventType.CHAT_MESSAGE, timestamp, content)

    @classmethod
    def commitment_ack(
        cls,
        timestamp: datetime,
        *,
        commitment_id: str,
        owed_by: str,
        owed_to: str,
        description: str,
        due_date: str = "",
        status: str = "acknowledged",
    ) -> Event:
        content = {
            "commitment_id": commitment_id,
            "owed_by": owed_by,
            "owed_to": owed_to,
            "description": description,
            "due_date": due_date,
            "status": status,
        }
        return cls(EventType.COMMITMENT_ACK, timestamp, content)

    @classmethod
    def focus_block(
        cls,
        timestamp: datetime,
        *,
        duration_minutes: int,
        topic: str = "",
        tags: list[str] | None = None,
    ) -> Event:
        content = {
            "duration_minutes": duration_minutes,
            "topic": topic,
            "tags": tags or [],
        }
        return cls(EventType.FOCUS_BLOCK, timestamp, content)
