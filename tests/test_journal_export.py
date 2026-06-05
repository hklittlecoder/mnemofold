"""Journal -> JSONL export: fidelity, tombstones, determinism."""

from datetime import UTC, datetime

from mnemofold.events import Event, EventStore, EventType
from mnemofold.storage import Journal


def make_event(i: int) -> Event:
    return Event(
        event_type=EventType.NOTE,
        timestamp=datetime(2026, 3, 1, 9, i, tzinfo=UTC),
        content={"title": f"note {i}"},
    )


class TestJournalExport:
    def test_empty_journal_exports_empty_file(self, tmp_path):
        out = tmp_path / "events.jsonl"
        with Journal(tmp_path / "j.db") as journal:
            assert journal.export_events_jsonl(out) == 0
        assert out.read_text(encoding="utf-8") == ""

    def test_export_roundtrips_through_event_store(self, tmp_path):
        events = [make_event(i) for i in range(4)]
        out = tmp_path / "events.jsonl"
        with Journal(tmp_path / "j.db") as journal:
            journal.extend(events)
            assert journal.export_events_jsonl(out) == 4
        store = EventStore(out)
        assert len(store) == 4
        assert [e.event_id for e in store] == [e.event_id for e in events]

    def test_tombstoned_events_excluded_by_default(self, tmp_path):
        events = [make_event(i) for i in range(3)]
        out = tmp_path / "events.jsonl"
        with Journal(tmp_path / "j.db") as journal:
            journal.extend(events)
            journal.record_tombstone(events[1].event_id, "forget")
            assert journal.export_events_jsonl(out) == 2
        exported = [e.event_id for e in EventStore(out)]
        assert events[1].event_id not in exported

    def test_include_tombstoned_flag(self, tmp_path):
        events = [make_event(i) for i in range(3)]
        out = tmp_path / "all.jsonl"
        with Journal(tmp_path / "j.db") as journal:
            journal.extend(events)
            journal.record_tombstone(events[1].event_id, "forget")
            assert journal.export_events_jsonl(out, include_tombstoned=True) == 3
        assert len(EventStore(out)) == 3

    def test_export_preserves_order_and_bytes(self, tmp_path):
        events = [make_event(i) for i in range(3)]
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        with Journal(tmp_path / "j.db") as journal:
            journal.extend(events)
            journal.export_events_jsonl(a)
            journal.export_events_jsonl(b)
        assert a.read_bytes() == b.read_bytes()
        lines = a.read_text(encoding="utf-8").splitlines()
        assert lines == [e.to_json() for e in events]
