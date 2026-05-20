"""Journal operational counters stay exact across the file lifecycle."""

from datetime import UTC, datetime

from mnemofold.events import Event, EventType
from mnemofold.storage import SCHEMA_VERSION, Journal, _genesis_chain_checksum


def make_event(i: int) -> Event:
    return Event(
        event_type=EventType.NOTE,
        timestamp=datetime(2026, 3, 1, 9, i, tzinfo=UTC),
        content={"title": f"note {i}"},
    )


class TestJournalStats:
    def test_empty_journal(self, tmp_path):
        with Journal(tmp_path / "j.db") as journal:
            stats = journal.stats()
            assert stats["frames"] == 0
            assert stats["tombstones"] == 0
            assert stats["head_checksum"] == _genesis_chain_checksum()
            assert stats["schema_version"] == SCHEMA_VERSION

    def test_counts_track_appends(self, tmp_path):
        with Journal(tmp_path / "j.db") as journal:
            journal.append(make_event(0))
            journal.extend([make_event(1), make_event(2)])
            stats = journal.stats()
            assert stats["frames"] == 3
            assert stats["head_checksum"] == journal.head_checksum()

    def test_tombstones_counted(self, tmp_path):
        with Journal(tmp_path / "j.db") as journal:
            event = make_event(0)
            journal.append(event)
            assert journal.record_tombstone(event.event_id, "test")
            # second tombstone for the same id does not add a row
            assert not journal.record_tombstone(event.event_id, "again")
            journal.record_tombstone("other-id", "test")
            assert journal.stats()["tombstones"] == 2

    def test_stats_stable_after_reopen(self, tmp_path):
        path = tmp_path / "j.db"
        with Journal(path) as journal:
            journal.append(make_event(0))
            before = journal.stats()
        with Journal(path) as journal:
            assert journal.stats() == before
