"""Golden bytes for the append-only event store file format.

Three scripted events (mail, note, task update) freeze the per-line
envelope layout, content-addressed ids and checksums. The store must
read this file back losslessly and refuse corrupted lines.
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mnemofold.events import Event, EventStore, EventType

FIXTURE = Path(__file__).parent / "fixtures" / "event_store_golden.jsonl"


def scripted_events() -> list[Event]:
    return [
        Event(
            event_type=EventType.MAIL_RECEIVED,
            timestamp=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
            content={
                "subject": "Release sync",
                "from": "ana@corp.example",
                "thread_id": "t-7",
            },
        ),
        Event(
            event_type=EventType.NOTE,
            timestamp=datetime(2026, 3, 2, 10, 30, tzinfo=UTC),
            content={"title": "standup notes", "text": "ship checklist by friday"},
        ),
        Event(
            event_type=EventType.TASK_UPDATE,
            timestamp=datetime(2026, 3, 2, 14, 0, tzinfo=UTC),
            content={"task_id": "task-42", "status": "in_progress", "owner": "bo"},
        ),
    ]


class TestEventStoreGolden:
    def test_append_matches_golden_bytes(self, tmp_path):
        path = tmp_path / "events.jsonl"
        store = EventStore(path)
        assert store.extend(scripted_events()) == 3
        assert path.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    def test_golden_loads_losslessly(self, tmp_path):
        path = tmp_path / "events.jsonl"
        shutil.copy(FIXTURE, path)
        store = EventStore(path)
        assert len(store) == 3
        original = scripted_events()
        assert [e.event_id for e in store] == [e.event_id for e in original]
        for loaded, expected in zip(store, original, strict=True):
            assert loaded.content == expected.content
            assert loaded.content_checksum == expected.content_checksum

    def test_reopen_is_idempotent(self, tmp_path):
        path = tmp_path / "events.jsonl"
        shutil.copy(FIXTURE, path)
        first = EventStore(path)
        assert first.extend(scripted_events()) == 0  # duplicates skipped
        assert path.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    def test_corrupt_line_refuses_load(self, tmp_path):
        path = tmp_path / "events.jsonl"
        text = FIXTURE.read_text(encoding="utf-8")
        lines = text.splitlines()
        lines[1] = lines[1].replace("standup notes", "tampered notes")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Corrupt event"):
            EventStore(path)
