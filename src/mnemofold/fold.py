"""Folding (consolidation): nightly fold of episodes into semantic memory.

The folding pipeline transforms episodic memories into durable semantic
facts with provenance. It performs near-duplicate merging with stable
winner selection, recurrence mining that proposes playbooks, and
produces fold reports citing every merge and every rejected candidate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


@dataclass(slots=True)
class MergeCandidate:
    """A pair of items considered for merging."""

    item_a_id: str
    item_b_id: str
    similarity: float
    merged_title: str
    merged_content: str


@dataclass(slots=True)
class MergeResult:
    """Result of a merge operation."""

    kept_id: str
    removed_id: str
    reason: str
    similarity: float
    provenance: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FoldReport:
    """A report of a folding pass."""

    fold_id: str
    timestamp: str
    items_before: int = 0
    items_after: int = 0
    merges: list[MergeResult] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    new_semantic: list[str] = field(default_factory=list)
    recurrence_proposals: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "timestamp": self.timestamp,
            "items_before": self.items_before,
            "items_after": self.items_after,
            "merges": [
                {
                    "kept_id": m.kept_id,
                    "removed_id": m.removed_id,
                    "reason": m.reason,
                    "similarity": m.similarity,
                    "provenance": list(m.provenance),
                }
                for m in self.merges
            ],
            "rejected": self.rejected,
            "new_semantic": list(self.new_semantic),
            "recurrence_proposals": self.recurrence_proposals,
        }


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _text_similarity(a: str, b: str) -> float:
    """Compute bigram Jaccard similarity of two texts.

    Simple but fast and deterministic. Used for near-duplicate detection.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    def bigrams(s: str) -> set[str]:
        s = s.lower()
        return {s[i : i + 2] for i in range(len(s) - 1)}

    bg_a = bigrams(a)
    bg_b = bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


@dataclass
class Folder:
    """Folding engine that consolidates episodic memory into semantic memory."""

    similarity_threshold: float = 0.75
    min_episodes_for_recurrence: int = 3

    def fold(
        self,
        store: MemoryStore,
        timestamp: str,
        fold_id: str | None = None,
    ) -> FoldReport:
        """Run one folding pass.

        1. Promote high-salience episodic items to semantic
        2. Merge near-duplicates in semantic tier
        3. Mine for recurrent patterns (playbook proposals)
        """
        if fold_id is None:
            fold_id = "fold_" + _content_hash(timestamp + str(self.similarity_threshold))

        episodic = store.items_by_tier(MemoryTier.EPISODIC)
        semantic = store.items_by_tier(MemoryTier.SEMANTIC)
        items_before = store.total_count()

        report = FoldReport(
            fold_id=fold_id,
            timestamp=timestamp,
            items_before=items_before,
        )

        # Step 1: promote high-salience episodic items to semantic
        promoted = self._promote_to_semantic(store, episodic, report)

        # Step 2: merge near-duplicates in semantic tier
        self._merge_near_duplicates(store, semantic + promoted, report)

        # Step 3: recurrence mining
        self._mine_recurrence(store, report)

        report.items_after = store.total_count()
        return report

    def _promote_to_semantic(
        self,
        store: MemoryStore,
        episodic_items: list[MemoryItem],
        report: FoldReport,
    ) -> list[MemoryItem]:
        """Promote episodic items with high access/salience to semantic."""
        promoted: list[MemoryItem] = []
        for item in episodic_items:
            if item.access_count >= 3 or item.salience >= 0.6:
                # Create a semantic version
                sem_item = MemoryItem(
                    item_id=item.item_id + "_sem",
                    tier=MemoryTier.SEMANTIC,
                    content=item.content,
                    title=item.title or item.item_id,
                    salience=item.salience,
                    access_count=item.access_count,
                    last_accessed=item.last_accessed,
                    tags=set(item.tags),
                    metadata={
                        **item.metadata,
                        "derived_from": item.item_id,
                        "fold_promoted": True,
                    },
                )
                store.add(sem_item)
                report.new_semantic.append(sem_item.item_id)
                promoted.append(sem_item)
        return promoted

    def _merge_near_duplicates(
        self,
        store: MemoryStore,
        items: list[MemoryItem],
        report: FoldReport,
    ) -> None:
        """Merge near-duplicate items in the semantic tier."""
        # Sort by ID for deterministic ordering
        sorted_items = sorted(items, key=lambda i: i.item_id)
        merged_ids: set[str] = set()

        for i in range(len(sorted_items)):
            a = sorted_items[i]
            if a.item_id in merged_ids:
                continue
            for j in range(i + 1, len(sorted_items)):
                b = sorted_items[j]
                if b.item_id in merged_ids:
                    continue

                sim = _text_similarity(a.content, b.content)
                if sim < self.similarity_threshold:
                    report.rejected.append(
                        {
                            "a": a.item_id,
                            "b": b.item_id,
                            "similarity": sim,
                            "reason": "below_threshold",
                        }
                    )
                    continue

                # Stable winner: keep the one with higher salience, then earlier ID
                if a.salience >= b.salience:
                    winner, loser = a, b
                else:
                    winner, loser = b, a

                # Merge: keep winner, add loser's metadata as provenance
                provenance = [
                    loser.item_id,
                    *winner.metadata.get("provenance", []),
                    *loser.metadata.get("provenance", []),
                ]
                winner.metadata["provenance"] = provenance
                winner.access_count = max(winner.access_count, loser.access_count)
                winner.salience = max(winner.salience, loser.salience)

                store.remove(loser.item_id)
                merged_ids.add(loser.item_id)

                report.merges.append(
                    MergeResult(
                        kept_id=winner.item_id,
                        removed_id=loser.item_id,
                        reason="near_duplicate",
                        similarity=sim,
                        provenance=provenance,
                    )
                )

    def _mine_recurrence(self, store: MemoryStore, report: FoldReport) -> None:
        """Mine for recurrent patterns that could become playbooks."""
        # Group semantic items by tag
        tag_groups: dict[str, list[MemoryItem]] = {}
        for item in store.items_by_tier(MemoryTier.SEMANTIC):
            for tag in item.tags:
                tag_groups.setdefault(tag, []).append(item)

        for tag, items in sorted(tag_groups.items()):
            if len(items) >= self.min_episodes_for_recurrence:
                report.recurrence_proposals.append(
                    {
                        "pattern_tag": tag,
                        "instance_count": len(items),
                        "example_titles": [i.title for i in items[:3]],
                        "confidence": min(1.0, len(items) / 10.0),
                    }
                )


def fold_idempotent_check(store: MemoryStore, folder: Folder, timestamp: str) -> bool:
    """Verify that folding twice produces the same result as folding once."""
    import copy

    store_copy = MemoryStore(
        working_set_size=store.working_set_size,
        promotion_salience_threshold=store.promotion_salience_threshold,
        demotion_salience_threshold=store.demotion_salience_threshold,
    )
    for item in [copy.deepcopy(i) for i in store._items.values()]:
        store_copy.add(item)

    # Fold once
    folder.fold(store_copy, timestamp, fold_id="fold1")
    state1 = store_copy.total_count()

    # Fold again
    folder.fold(store_copy, timestamp, fold_id="fold2")
    state2 = store_copy.total_count()

    return state1 == state2
