"""Randomized journal histories: exports stay faithful across reopens.

For seeded event batches with random tombstones: the exported JSONL
always re-imports to the exact surviving event sequence, and exporting
before and after a reopen yields identical bytes.
"""

import random
from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventStore, EventType
from mnemofold.storage import Journal

BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def build(path, seed: int, n: int) -> list[Event]:
    rng = random.Random(seed)
    events = [
        Event(
            event_type=EventType.NOTE,
            timestamp=BASE + timedelta(minutes=i * 7),
            content={"title": f"note {i}", "body": "x" * rng.randint(1, 20)},
        )
        for i in range(n)
    ]
    with Journal(path) as journal:
        journal.extend(events)
        for event in events:
            if rng.random() < 0.3:
                journal.record_tombstone(event.event_id, "sweep")
    return events


class TestExportProperties:
    def test_export_matches_surviving_events(self, tmp_path):
        for seed in range(8):
            db = tmp_path / f"j{seed}.db"
            out = tmp_path / f"e{seed}.jsonl"
            build(db, seed, 12)
            with Journal(db) as journal:
                written = journal.export_events_jsonl(out)
                survivors = [
                    e.event_id
                    for e in journal.iter_events()
                    if journal.tombstone(e.event_id) is None
                ]
            assert written == len(survivors), seed
            assert [e.event_id for e in EventStore(out)] == survivors, seed

    def test_reopen_exports_identical_bytes(self, tmp_path):
        for seed in range(5):
            db = tmp_path / f"r{seed}.db"
            a, b = tmp_path / f"a{seed}.jsonl", tmp_path / f"b{seed}.jsonl"
            build(db, seed, 10)
            with Journal(db) as journal:
                journal.export_events_jsonl(a)
            with Journal(db) as journal:
                journal.export_events_jsonl(b)
            assert a.read_bytes() == b.read_bytes(), seed

    def test_append_after_export_extends_cleanly(self, tmp_path):
        db = tmp_path / "app.db"
        first_out, second_out = tmp_path / "f.jsonl", tmp_path / "s.jsonl"
        build(db, 99, 5)
        with Journal(db) as journal:
            journal.export_events_jsonl(first_out)
        with Journal(db) as journal:
            journal.append(
                Event(
                    event_type=EventType.NOTE,
                    timestamp=BASE + timedelta(hours=5),
                    content={"title": "appended"},
                )
            )
            journal.export_events_jsonl(second_out)
        first_ids = [e.event_id for e in EventStore(first_out)]
        second_ids = [e.event_id for e in EventStore(second_out)]
        assert second_ids[: len(first_ids)] == first_ids
        assert len(second_ids) == len(first_ids) + 1
