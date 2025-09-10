"""Workspace snapshot and diff tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mnemofold.events import Event, EventType
from mnemofold.workspace import Workspace, diff_snapshots


def _notes(count: int) -> list[Event]:
    return [
        Event(
            EventType.NOTE,
            datetime(2025, 1, 1, 9, i, tzinfo=UTC),
            {"text": f"note {i}", "title": f"n{i}"},
        )
        for i in range(count)
    ]


class TestWorkspaceSnapshot:
    def test_snapshot_tracks_ingested_events(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            before = ws.snapshot()
            assert before["memories"]["episodic"] == []
            assert before["commitments"] == {}
            ws.ingest_events(_notes(3))
            after = ws.snapshot()
            assert len(after["memories"]["episodic"]) == 3
            diff = diff_snapshots(before, after)
            assert not diff["empty"]
            assert len(diff["memories"]["episodic"]["added"]) == 3
            assert diff["memories"]["episodic"]["removed"] == []
            assert diff["digest_changed"]

    def test_rebuild_reproduces_an_identical_snapshot(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(2))
            first = ws.snapshot()
            ws.rebuild()
            assert diff_snapshots(first, ws.snapshot())["empty"]

    def test_forget_shows_removal_and_tombstone(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            ws.ingest_events(_notes(1))
            before = ws.snapshot()
            victim = before["memories"]["episodic"][0]
            ws.forget(victim, now="2025-01-02T00:00:00+00:00", reason="test cleanup")
            after = ws.snapshot()
            diff = diff_snapshots(before, after)
            assert victim in diff["memories"]["episodic"]["removed"]
            assert victim in after["tombstones"]
            assert diff["tombstones_added"] == [victim]

    def test_identical_snapshots_diff_empty(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            snap = ws.snapshot()
            assert diff_snapshots(snap, ws.snapshot())["empty"]

    def test_snapshot_reflects_journal_head(self, tmp_path: Path):
        with Workspace(tmp_path / "ws") as ws:
            first = ws.snapshot()
            ws.ingest_events(_notes(1))
            second = ws.snapshot()
            assert first["head"] != second["head"]
            assert second["head"] == ws.journal.head_checksum()
