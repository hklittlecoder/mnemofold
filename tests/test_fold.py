"""Tests for the folding (consolidation) module."""

from __future__ import annotations

from mnemofold.fold import Folder, _text_similarity, fold_idempotent_check
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


class TestTextSimilarity:
    def test_identical_texts(self):
        assert _text_similarity("hello world", "hello world") == 1.0

    def test_empty_strings(self):
        assert _text_similarity("", "") == 0.0
        assert _text_similarity("hello", "") == 0.0

    def test_different_texts(self):
        sim = _text_similarity("hello world", "completely different content here")
        assert sim < 0.5

    def test_similar_texts(self):
        sim = _text_similarity("the quick brown fox", "the quick brown frog")
        assert sim > 0.5


class TestFolder:
    def _make_episodic_store(self, n: int = 5, prefix: str = "ep") -> MemoryStore:
        store = MemoryStore()
        for i in range(n):
            item = MemoryItem(
                item_id=f"{prefix}_{i}",
                tier=MemoryTier.EPISODIC,
                content=f"Episode {i}: this is some content about topic {i % 3}",
                title=f"Episode {i}",
                salience=0.1 + (i * 0.15),
                access_count=i,
                tags={f"topic_{i % 3}"},
            )
            store.add(item)
        return store

    def test_fold_creates_semantic_items(self):
        store = self._make_episodic_store(n=5)
        folder = Folder(similarity_threshold=0.8)
        before_sem = len(store.items_by_tier(MemoryTier.SEMANTIC))
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        after_sem = len(store.items_by_tier(MemoryTier.SEMANTIC))
        # High-access / high-salience items should be promoted
        assert after_sem > before_sem
        assert len(report.new_semantic) > 0

    def test_fold_report_has_counts(self):
        store = self._make_episodic_store(n=5)
        folder = Folder()
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        assert report.items_before > 0
        assert report.fold_id.startswith("fold_")
        assert report.timestamp == "2024-01-01T00:00:00+00:00"

    def test_near_duplicate_merging(self):
        store = MemoryStore()
        # Two very similar items
        a = MemoryItem(
            "dup_a",
            MemoryTier.SEMANTIC,
            "The project deadline is next Friday and we need to finish soon",
            title="Reminder",
            salience=0.5,
        )
        b = MemoryItem(
            "dup_b",
            MemoryTier.SEMANTIC,
            "The project deadline is next Friday and we need to finish quickly",
            title="Reminder 2",
            salience=0.6,
        )
        store.add(a)
        store.add(b)
        folder = Folder(similarity_threshold=0.7)
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        # The two near-duplicates should be merged
        merge_count = sum(1 for m in report.merges if m.reason == "near_duplicate")
        assert merge_count >= 1

    def test_merge_preserves_provenance(self):
        store = MemoryStore()
        a = MemoryItem("a", MemoryTier.SEMANTIC, "similar content alpha", salience=0.5)
        b = MemoryItem("b", MemoryTier.SEMANTIC, "similar content beta", salience=0.4)
        store.add(a)
        store.add(b)
        folder = Folder(similarity_threshold=0.5)
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        # After merge, the kept item should have provenance
        for m in report.merges:
            kept = store.get(m.kept_id)
            if kept:
                assert "provenance" in kept.metadata
                assert m.removed_id in kept.metadata["provenance"]

    def test_recurrence_proposals(self):
        store = MemoryStore()
        # Create multiple items with same tag
        for i in range(5):
            item = MemoryItem(
                f"r_{i}",
                MemoryTier.SEMANTIC,
                f"Recurring task version {i}",
                title=f"Task {i}",
                tags={"recurring", f"type_{i % 2}"},
            )
            store.add(item)
        folder = Folder(min_episodes_for_recurrence=3)
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        assert len(report.recurrence_proposals) > 0
        # "recurring" tag should have 5 instances
        recurring = [p for p in report.recurrence_proposals if p["pattern_tag"] == "recurring"]
        assert len(recurring) == 1
        assert recurring[0]["instance_count"] == 5

    def test_rejected_candidates_recorded(self):
        store = self._make_episodic_store(n=5)
        folder = Folder(similarity_threshold=0.99)  # very high threshold
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        # Should have some rejected pairs (below threshold)
        assert len(report.rejected) > 0
        for r in report.rejected:
            assert "reason" in r
            assert "similarity" in r

    def test_fold_is_deterministic(self):
        store1 = self._make_episodic_store(n=6)
        store2 = self._make_episodic_store(n=6)
        folder = Folder(similarity_threshold=0.7)

        r1 = folder.fold(store1, "2024-01-01T00:00:00+00:00", fold_id="test1")
        r2 = folder.fold(store2, "2024-01-01T00:00:00+00:00", fold_id="test1")

        assert r1.items_before == r2.items_before
        assert r1.items_after == r2.items_after
        assert len(r1.merges) == len(r2.merges)

    def test_fold_idempotent(self):
        store = self._make_episodic_store(n=8)
        folder = Folder(similarity_threshold=0.7)
        assert fold_idempotent_check(store, folder, "2024-01-01T00:00:00+00:00")

    def test_report_to_dict(self):
        store = self._make_episodic_store(n=3)
        folder = Folder()
        report = folder.fold(store, "2024-01-01T00:00:00+00:00")
        d = report.to_dict()
        assert d["fold_id"] == report.fold_id
        assert "merges" in d
        assert "rejected" in d
        assert "new_semantic" in d


class TestWorkflowSequenceMining:
    def _workflow_item(self, run: str, step: str, minute: int) -> MemoryItem:
        return MemoryItem(
            item_id=f"{run}_{step}",
            tier=MemoryTier.EPISODIC,
            content=f"{step} for {run}",
            created_at=f"2025-03-10T{minute:02d}:00:00+00:00",
            metadata={"workflow": "release", "run_id": run, "step": step},
        )

    def _store_with_runs(self) -> MemoryStore:
        store = MemoryStore()
        for run in ("r1", "r2", "r3"):
            for minute, step in ((10, "build"), (20, "test"), (30, "ship")):
                store.add(self._workflow_item(run, step, minute))
        # one outlier run with a different sequence
        store.add(self._workflow_item("r4", "build", 10))
        store.add(self._workflow_item("r4", "ship", 20))
        return store

    def test_repeated_sequence_becomes_proposal(self):
        folder = Folder(min_episodes_for_recurrence=3)
        report = folder.fold(self._store_with_runs(), "2025-03-11T00:00:00+00:00")
        seqs = [p for p in report.recurrence_proposals if p.get("kind") == "workflow_sequence"]
        assert len(seqs) == 1
        proposal = seqs[0]
        assert proposal["workflow"] == "release"
        assert proposal["steps"] == ["build", "test", "ship"]
        assert proposal["run_count"] == 3
        assert proposal["run_ids"] == ["r1", "r2", "r3"]
        assert proposal["confidence"] == 0.3

    def test_outlier_sequence_not_proposed(self):
        folder = Folder(min_episodes_for_recurrence=3)
        report = folder.fold(self._store_with_runs(), "2025-03-11T00:00:00+00:00")
        seqs = [p for p in report.recurrence_proposals if p.get("kind") == "workflow_sequence"]
        assert all(p["steps"] != ["build", "ship"] for p in seqs)

    def test_steps_ordered_by_creation_time(self):
        store = MemoryStore()
        # inserted out of order; created_at must drive the sequence
        store.add(self._workflow_item("r1", "ship", 30))
        store.add(self._workflow_item("r1", "build", 10))
        store.add(self._workflow_item("r1", "test", 20))
        store.add(self._workflow_item("r2", "ship", 30))
        store.add(self._workflow_item("r2", "build", 10))
        store.add(self._workflow_item("r2", "test", 20))
        store.add(self._workflow_item("r3", "build", 10))
        store.add(self._workflow_item("r3", "test", 20))
        store.add(self._workflow_item("r3", "ship", 30))
        report = Folder(min_episodes_for_recurrence=3).fold(store, "2025-03-11T00:00:00+00:00")
        seqs = [p for p in report.recurrence_proposals if p.get("kind") == "workflow_sequence"]
        assert seqs[0]["steps"] == ["build", "test", "ship"]

    def test_items_without_workflow_metadata_ignored(self):
        store = MemoryStore()
        store.add(MemoryItem("plain", MemoryTier.EPISODIC, "no metadata here"))
        report = Folder().fold(store, "2025-03-11T00:00:00+00:00")
        assert report.recurrence_proposals == []

    def test_tag_proposals_labeled_with_kind(self):
        store = MemoryStore()
        for i in range(3):
            store.add(
                MemoryItem(
                    f"t{i}",
                    MemoryTier.SEMANTIC,
                    f"content {i}",
                    tags={"weekly"},
                )
            )
        report = Folder(min_episodes_for_recurrence=3).fold(store, "2025-03-11T00:00:00+00:00")
        tags = [p for p in report.recurrence_proposals if p.get("kind") == "tag_frequency"]
        assert len(tags) == 1
        assert tags[0]["pattern_tag"] == "weekly"
