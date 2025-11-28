"""Tests for meeting prep module."""

from __future__ import annotations

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.prep import MeetingPrepper, measure_coverage, verify_citations


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


class TestEvidenceAgenda:
    def _store(self) -> MemoryStore:
        store = MemoryStore()
        entries = [
            ("cm1", "Alice owes the budget numbers to Bob", "Budget promise", {"commitment"}),
            ("dc1", "Decision pending on the budget storage vendor", "Vendor choice", {"decision"}),
            ("pr1", "Alice profile and team background", "Alice", {"person"}),
            ("nt1", "Notes about the alpha rollout plan", "Rollout notes", {"note"}),
        ]
        for item_id, content, title, tags in entries:
            store.add(
                MemoryItem(
                    item_id=item_id,
                    tier=MemoryTier.SEMANTIC,
                    content=content,
                    title=title,
                    tags=set(tags),
                )
            )
        return store

    def test_agenda_sections_ordered_commitments_first(self):
        prep = MeetingPrepper(store=self._store()).prepare("mtg1", "Alpha budget sync", ["alice"])
        assert prep.agenda_items
        assert prep.agenda_items[0].startswith("Review open commitments")
        assert prep.agenda_items[1].startswith("Confirm pending decisions")
        assert prep.agenda_items[-2:] == ["Open discussion", "Action items"]

    def test_every_evidence_line_cites_ids(self):
        prep = MeetingPrepper(store=self._store()).prepare("mtg1", "Alpha budget sync", ["alice"])
        evidence_lines = [a for a in prep.agenda_items if "cites" in a]
        assert evidence_lines
        for line in evidence_lines:
            cited = line.split("cites")[1].strip()
            assert cited
            for cid in cited.split(", "):
                assert cid in {i.item_id for i in prep.items}

    def test_empty_packet_keeps_closing_slots(self):
        prep = MeetingPrepper(store=MemoryStore()).prepare("mtg1", "Nothing sync", [])
        assert prep.agenda_items == ["Open discussion", "Action items"]

    def test_agenda_is_deterministic(self):
        first = MeetingPrepper(store=self._store()).prepare("m", "Alpha budget sync", ["alice"])
        second = MeetingPrepper(store=self._store()).prepare("m", "Alpha budget sync", ["alice"])
        assert first.agenda_items == second.agenda_items


class TestPrepCoverage:
    def _store(self) -> MemoryStore:
        store = MemoryStore()
        store.add(
            MemoryItem(
                item_id="alice",
                tier=MemoryTier.SEMANTIC,
                content="Alice leads the alpha project",
                title="Alice",
                tags={"person"},
            )
        )
        store.add(
            MemoryItem(
                item_id="commit1",
                tier=MemoryTier.SEMANTIC,
                content="Alice owes the alpha status update",
                title="Status promise",
                tags={"commitment"},
            )
        )
        store.add(
            MemoryItem(
                item_id="noise",
                tier=MemoryTier.SEMANTIC,
                content="unrelated chatter about the weather",
                title="Noise",
            )
        )
        return store

    def test_full_coverage(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        report = measure_coverage(prep, ["alice", "commit1"])
        assert report.covered == 2
        assert report.missing == []
        assert report.ratio == 1.0

    def test_partial_coverage_lists_missing(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        report = measure_coverage(prep, ["alice", "never_surfaced"])
        assert report.covered == 1
        assert report.missing == ["never_surfaced"]
        assert report.ratio == 0.5

    def test_empty_expectation_is_ratio_one(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        report = measure_coverage(prep, [])
        assert report.expected == 0
        assert report.ratio == 1.0

    def test_duplicate_expectations_counted_once(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        report = measure_coverage(prep, ["alice", "alice", "commit1"])
        assert report.expected == 2
        assert report.covered == 2

    def test_category_coverage_tracks_per_category_hits(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        cats = {"alice": "person", "commit1": "commitment", "missing_one": "decision"}
        report = measure_coverage(
            prep, ["alice", "commit1", "missing_one"], expected_categories=cats
        )
        assert "person" in report.per_category
        assert report.per_category["person"] == (1, 1)
        assert report.per_category["commitment"] == (1, 1)
        assert report.per_category["decision"] == (1, 0)
        assert 0.0 < report.category_coverage < 1.0

    def test_category_coverage_full_when_all_hit(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        cats = {"alice": "person", "commit1": "commitment"}
        report = measure_coverage(prep, ["alice", "commit1"], expected_categories=cats)
        assert report.category_coverage == 1.0

    def test_category_coverage_empty_defaults_to_one(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        report = measure_coverage(prep, ["alice", "commit1"])
        assert report.category_coverage == 1.0
        assert report.per_category == {}

    def test_recall_by_category_per_category(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        cats = {"alice": "person", "commit1": "commitment", "miss_d": "decision"}
        report = measure_coverage(prep, ["alice", "commit1", "miss_d"], expected_categories=cats)
        assert report.recall_by_category("person") == 1.0
        assert report.recall_by_category("commitment") == 1.0
        assert report.recall_by_category("decision") == 0.0

    def test_recall_by_category_unknown_returns_one(self):
        prep = MeetingPrepper(store=self._store()).prepare("m", "alpha sync", ["alice"])
        report = measure_coverage(prep, ["alice"], expected_categories={"alice": "person"})
        assert report.recall_by_category("nonexistent_category") == 1.0


class TestPrepPacketProperties:
    def _store(self, n: int = 6) -> MemoryStore:
        store = MemoryStore()
        for i in range(n):
            store.add(
                MemoryItem(
                    item_id=f"m{i}",
                    tier=MemoryTier.EPISODIC,
                    content=f"budget planning notes variant {i}",
                    title=f"Note {i}",
                    tags={"note"},
                )
            )
        return store

    def test_max_items_cap_respected(self):
        prep = MeetingPrepper(store=self._store(), max_items=3).prepare(
            "mtg", "budget planning", []
        )
        assert prep.total_items == 3
        assert len(prep.items) == 3

    def test_counts_are_consistent(self):
        prep = MeetingPrepper(store=self._store()).prepare("mtg", "budget planning", [])
        assert prep.total_items == len(prep.items) == len(prep.cited_sources)

    def test_citations_resolve_both_directions(self):
        store = self._store()
        prep = MeetingPrepper(store=store).prepare("mtg", "budget planning", [])
        assert verify_citations(prep, store)
        store.remove(prep.cited_sources[0])
        assert not verify_citations(prep, store)

    def test_html_packet_escapes_hostile_text(self):
        store = MemoryStore()
        store.add(
            MemoryItem(
                item_id="x",
                tier=MemoryTier.SEMANTIC,
                content="<script>alert(1)</script> budget",
                title="<img onerror=budget>",
                tags={"note"},
            )
        )
        prep = MeetingPrepper(store=store).prepare("mtg", "budget", [])
        page = prep.to_html()
        assert "<script>" not in page
        assert "&lt;script&gt;" in page
        assert "<img" not in page

    def test_markdown_packet_structure(self):
        prep = MeetingPrepper(store=self._store(2)).prepare("mtg", "budget planning", [])
        markdown = prep.to_markdown()
        assert markdown.startswith("# Meeting Prep: budget planning")
        assert "## Agenda" in markdown
        assert "## Background (2 items)" in markdown
        assert "*Sources cited: 2*" in markdown

    def test_long_summaries_are_truncated(self):
        store = MemoryStore()
        store.add(
            MemoryItem(
                item_id="long",
                tier=MemoryTier.SEMANTIC,
                content="budget " * 100,
                title="Long",
                tags={"note"},
            )
        )
        prep = MeetingPrepper(store=store).prepare("mtg", "budget", [])
        assert prep.items[0].summary.endswith("...")
        assert len(prep.items[0].summary) == 203

    def test_prepare_is_deterministic(self):
        first = MeetingPrepper(store=self._store()).prepare("mtg", "budget planning", [])
        second = MeetingPrepper(store=self._store()).prepare("mtg", "budget planning", [])
        assert first.to_markdown() == second.to_markdown()
        assert first.to_html() == second.to_html()

    def test_html_escapes_item_content(self):
        store = MemoryStore()
        store.add(
            MemoryItem(
                item_id="bad",
                tier=MemoryTier.SEMANTIC,
                content="hello <b>bold</b> world budget",
                title="ok",
                tags={"note"},
            )
        )
        prep = MeetingPrepper(store=store).prepare("m", "budget", [])
        page = prep.to_html()
        assert "<b>bold</b>" not in page
        assert "&lt;b&gt;bold&lt;/b&gt;" in page
