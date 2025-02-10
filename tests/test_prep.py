"""Tests for meeting prep module."""

from __future__ import annotations

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.prep import MeetingPrepper, verify_citations


class TestMeetingPrepper:
    def _make_store(self) -> MemoryStore:
        store = MemoryStore()
        items = [
            ("alice_profile", "Alice is the PM", "Alice profile", {"person", "team"}),
            ("bob_profile", "Bob is an engineer", "Bob profile", {"person", "team"}),
            ("project_x", "Project X is about building", "Project X", {"project"}),
            (
                "commitment_1",
                "Alice owes Bob a report by Friday",
                "Report commitment",
                {"commitment"},
            ),
            ("decision_1", "We decided to use Postgres", "Architecture decision", {"decision"}),
            ("note_1", "Some meeting notes from last week", "Meeting notes", {"note"}),
            ("unrelated", "Something about cooking", "Cooking recipe", {"food"}),
        ]
        for iid, content, title, tags in items:
            item = MemoryItem(
                iid, MemoryTier.SEMANTIC, content, title=title, tags=set(tags), salience=0.5
            )
            store.add(item)
        return store

    def test_prep_creates_packet(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare(
            meeting_id="m1",
            meeting_title="Project X sync",
            attendees=["Alice", "Bob"],
        )
        assert prep.meeting_id == "m1"
        assert len(prep.attendee_names) == 2
        assert prep.total_items > 0

    def test_prep_includes_relevant_items(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "Project X", ["Alice"])
        item_ids = {it.item_id for it in prep.items}
        assert "project_x" in item_ids
        assert "alice_profile" in item_ids

    def test_prep_excludes_unrelated(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "Project meeting", ["Alice"])
        item_ids = {it.item_id for it in prep.items}
        # Unrelated cooking item should not be in a project meeting prep
        assert "unrelated" not in item_ids

    def test_agenda_items(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "Project X", ["Alice"])
        assert len(prep.agenda_items) >= 2

    def test_citations_all_resolve(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "Project X", ["Alice"])
        assert verify_citations(prep, store)

    def test_markdown_output(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "Test Meeting", ["Alice"])
        md = prep.to_markdown()
        assert "Meeting Prep" in md
        assert "Test Meeting" in md
        assert "Agenda" in md

    def test_html_output(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "Test Meeting", ["Alice"])
        h = prep.to_html()
        assert "<html" in h
        assert "Test Meeting" in h
        assert "<h1>" in h

    def test_html_escapes_title(self):
        store = self._make_store()
        prepper = MeetingPrepper(store)
        prep = prepper.prepare("m1", "<script>alert(1)</script>", ["Alice"])
        h = prep.to_html()
        assert "<script>" not in h
        assert "&lt;script&gt;" in h

    def test_max_items_limit(self):
        store = MemoryStore()
        for i in range(50):
            item = MemoryItem(
                f"it_{i}",
                MemoryTier.SEMANTIC,
                f"content about project {i}",
                title=f"Item {i}",
                tags={"project"},
            )
            store.add(item)
        prepper = MeetingPrepper(store, max_items=10)
        prep = prepper.prepare("m1", "project", ["Alice"])
        assert prep.total_items <= 10
