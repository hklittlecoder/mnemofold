"""Memory tiers: working set, episodic, semantic, procedural.

Implements a four-tier memory model with promotion and demotion rules
driven by salience and access patterns. The working set has a bounded
size; items are evicted based on recency and importance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _moment(value: str) -> datetime | None:
    """Parse an ISO instant (naive means UTC); None when unparseable."""
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class MemoryTier(StrEnum):
    """Memory tiers from most to least accessible."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass(slots=True)
class MemoryItem:
    """An item stored in memory."""

    item_id: str
    tier: MemoryTier
    content: str
    title: str = ""
    salience: float = 0.0
    access_count: int = 0
    last_accessed: str = ""
    created_at: str = ""
    tags: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    pinned: bool = False
    retain_until: str = ""  # retention hold: never forget before this instant

    def __post_init__(self) -> None:
        if isinstance(self.tier, str):
            self.tier = MemoryTier(self.tier)
        if isinstance(self.tags, list):
            self.tags = set(self.tags)


@dataclass
class MemoryStore:
    """Multi-tier memory store with promotion and demotion.

    Tiers (most accessible first):
    - working: currently-active context, bounded size
    - episodic: event-based memories (episodes)
    - semantic: consolidated facts and knowledge
    - procedural: learned procedures / playbooks

    Promotion: items move up tiers when accessed frequently or
    when salience crosses a threshold.
    Demotion: items move down tiers when not accessed for a while
    or when the working set is full.
    """

    _items: dict[str, MemoryItem] = field(default_factory=dict)
    working_set_size: int = 50
    promotion_salience_threshold: float = 0.7
    demotion_salience_threshold: float = 0.3

    def add(self, item: MemoryItem) -> None:
        """Add an item to memory."""
        self._items[item.item_id] = item
        if item.tier == MemoryTier.WORKING:
            self._enforce_working_set_bounds()

    def get(self, item_id: str) -> MemoryItem | None:
        """Get an item by ID, recording access."""
        item = self._items.get(item_id)
        if item is not None:
            item.access_count += 1
        return item

    def remove(self, item_id: str) -> None:
        """Remove an item from memory."""
        if item_id in self._items:
            del self._items[item_id]

    def promote(self, item_id: str) -> bool:
        """Promote an item to the next higher tier.

        Returns True if promoted, False if already at top tier
        or item not found.
        """
        item = self._items.get(item_id)
        if item is None:
            return False
        tiers = [
            MemoryTier.PROCEDURAL,
            MemoryTier.SEMANTIC,
            MemoryTier.EPISODIC,
            MemoryTier.WORKING,
        ]
        idx = tiers.index(item.tier)
        if idx >= len(tiers) - 1:
            return False
        item.tier = tiers[idx + 1]
        if item.tier == MemoryTier.WORKING:
            self._enforce_working_set_bounds()
        return True

    def demote(self, item_id: str) -> bool:
        """Demote an item to the next lower tier.

        Returns True if demoted, False if already at bottom tier
        or item not found.
        """
        item = self._items.get(item_id)
        if item is None or item.pinned:
            return False
        tiers = [
            MemoryTier.PROCEDURAL,
            MemoryTier.SEMANTIC,
            MemoryTier.EPISODIC,
            MemoryTier.WORKING,
        ]
        idx = tiers.index(item.tier)
        if idx <= 0:
            return False
        item.tier = tiers[idx - 1]
        return True

    def items_by_tier(self, tier: MemoryTier) -> list[MemoryItem]:
        """Get all items in a given tier."""
        if isinstance(tier, str):
            tier = MemoryTier(tier)
        return [i for i in self._items.values() if i.tier == tier]

    def working_set(self) -> list[MemoryItem]:
        """Get all items in the working set (sorted by salience desc)."""
        items = self.items_by_tier(MemoryTier.WORKING)
        return sorted(items, key=lambda i: i.salience, reverse=True)

    def _enforce_working_set_bounds(self) -> None:
        """Evict lowest-salience items if working set exceeds size limit.

        Pinned items are never evicted. Evicted items are demoted to
        episodic tier.
        """
        working = [i for i in self._items.values() if i.tier == MemoryTier.WORKING]
        if len(working) <= self.working_set_size:
            return
        # Sort by salience ascending, but pinned items sort to the end
        working.sort(key=lambda i: (i.pinned, i.salience))
        evict_count = len(working) - self.working_set_size
        for item in working[:evict_count]:
            if item.pinned:
                continue
            # Demote to episodic
            item.tier = MemoryTier.EPISODIC

    def tier_counts(self) -> dict[MemoryTier, int]:
        """Return count of items per tier."""
        counts: dict[MemoryTier, int] = {}
        for tier in MemoryTier:
            counts[tier] = len(self.items_by_tier(tier))
        return counts

    def search_by_tag(self, tag: str) -> list[MemoryItem]:
        """Find items with a given tag."""
        return [i for i in self._items.values() if tag in i.tags]

    def total_count(self) -> int:
        """Total number of items across all tiers."""
        return len(self._items)

    def record_access(self, item_id: str, now: str) -> bool:
        """Record an access at an explicit instant.

        Deterministic counterpart to the implicit counting in
        :meth:`get`: callers that operate on simulated time pass the
        instant in, so ``last_accessed`` stays reproducible. Returns
        False when the item does not exist.
        """
        item = self._items.get(item_id)
        if item is None:
            return False
        item.access_count += 1
        item.last_accessed = now
        return True

    def under_retention(self, item_id: str, now: str) -> bool:
        """True while the item sits inside its retention window.

        A retention hold (``retain_until``) shields the item from
        forgetting-style demotion until the instant passes; the bound is
        exclusive (at ``now == retain_until`` the hold is over).
        """
        item = self._items.get(item_id)
        if item is None or not item.retain_until:
            return False
        hold = _moment(item.retain_until)
        moment = _moment(now)
        if hold is None or moment is None:
            return False
        return moment < hold
