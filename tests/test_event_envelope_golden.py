"""Golden bytes for the schema-versioned event envelope.

The envelope (including the content-addressed event id and checksum) is
frozen here so any change to event serialization — key names, canonical
JSON style, or id derivation — is a deliberate, reviewed change.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mnemofold.events import Event, EventType

FIXTURE = Path(__file__).parent / "fixtures" / "event_envelope_golden.json"


def make_event() -> Event:
    return Event(
        event_type=EventType.MAIL_RECEIVED,
        timestamp=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
        content={
            "subject": "Release sync",
            "from": "ana@corp.example",
            "thread_id": "t-7",
        },
    )


class TestEventEnvelopeGolden:
    def test_to_json_matches_golden_bytes(self):
        assert make_event().to_json() == FIXTURE.read_text(encoding="utf-8")

    def test_ids_match_golden(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        event = make_event()
        assert event.event_id == golden["event_id"]
        assert event.content_checksum == golden["content_checksum"]
        assert event.event_id == "evt_" + event.content_checksum[:16]

    def test_from_envelope_roundtrip(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert Event.from_envelope(golden) == make_event()

    def test_tampered_golden_content_is_rejected(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        golden["content"]["subject"] = "Tampered subject"
        with pytest.raises(ValueError):
            Event.from_envelope(golden)

    def test_regeneration_is_stable(self):
        assert make_event().to_json() == make_event().to_json()
