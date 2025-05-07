"""Decay and forgetting: per-tier retention curves and tombstone semantics.

Implements Ebbinghaus-style forgetting curves, protected/pinned records,
grace periods, tombstone semantics, and property-testable invariants.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


class TombstoneState(StrEnum):
    """State of a tombstoned memory item."""

    ACTIVE = "active"
    GRACE = "grace"
    TOMBSTONED = "tombstoned"
    PURGED = "purged"


@dataclass(slots=True)
class RetentionPolicy:
    """Retention policy for a memory tier."""

    tier: MemoryTier
    half_life_days: float = 30.0
    grace_days: float = 7.0
    min_salience: float = 0.05
    max_age_days: float = 365.0

    def decay_factor(self, days: float) -> float:
        return math.exp(-days * math.log(2) / self.half_life_days)

    def decayed_salience(self, item: MemoryItem, now: str) -> float:
        age = _age_days(item, now)
        return item.salience * self.decay_factor(age)

    def should_decay(self, item: MemoryItem, now: str) -> bool:
        if item.pinned:
            return False
        age = _age_days(item, now)
        if age > self.max_age_days:
            return True
        return self.decayed_salience(item, now) < self.min_salience


def _age_days(item: MemoryItem, now: str) -> float:
    try:
        t_now = datetime.fromisoformat(now)
        ref_str = item.last_accessed or item.created_at
        if not ref_str:
            return 0.0
        t_ref = datetime.fromisoformat(ref_str)
    except (ValueError, TypeError):
        return 0.0
    if t_now.tzinfo is None:
        t_now = t_now.replace(tzinfo=UTC)
    if t_ref.tzinfo is None:
        t_ref = t_ref.replace(tzinfo=UTC)
    return max(0.0, (t_now - t_ref).total_seconds() / 86400.0)


DEFAULT_POLICIES: dict[MemoryTier, RetentionPolicy] = {
    MemoryTier.WORKING: RetentionPolicy(
        MemoryTier.WORKING, half_life_days=1.0, grace_days=1.0, max_age_days=7.0
    ),
    MemoryTier.EPISODIC: RetentionPolicy(
        MemoryTier.EPISODIC, half_life_days=14.0, grace_days=3.0, max_age_days=90.0
    ),
    MemoryTier.SEMANTIC: RetentionPolicy(
        MemoryTier.SEMANTIC, half_life_days=90.0, grace_days=7.0, max_age_days=365.0
    ),
    MemoryTier.PROCEDURAL: RetentionPolicy(
        MemoryTier.PROCEDURAL, half_life_days=180.0, grace_days=14.0, max_age_days=730.0
    ),
}


@dataclass
class DecayEngine:
    """Applies decay and forgetting to a memory store."""

    policies: dict[MemoryTier, RetentionPolicy] = field(
        default_factory=lambda: dict(DEFAULT_POLICIES)
    )
    protected_tags: set[str] = field(default_factory=lambda: {"legal_hold", "protected"})
    _tombstones: dict[str, TombstoneState] = field(default_factory=dict)

    def is_protected(self, item: MemoryItem) -> bool:
        if item.pinned:
            return True
        return bool(item.tags & self.protected_tags)

    def apply_decay(self, store: MemoryStore, now: str) -> dict[str, int]:
        stats = {"demoted": 0, "tombstoned": 0, "purged": 0, "protected_skipped": 0}
        tiers = [MemoryTier.WORKING, MemoryTier.EPISODIC, MemoryTier.SEMANTIC]
        tier_below = {
            MemoryTier.WORKING: MemoryTier.EPISODIC,
            MemoryTier.EPISODIC: MemoryTier.SEMANTIC,
            MemoryTier.SEMANTIC: MemoryTier.PROCEDURAL,
        }
        for tier in tiers:
            for item in list(store.items_by_tier(tier)):
                if self.is_protected(item):
                    stats["protected_skipped"] += 1
                    continue
                policy = self.policies.get(tier)
                if policy and policy.should_decay(item, now):
                    item.tier = tier_below[tier]
                    stats["demoted"] += 1
        # Handle procedural tier (bottom): tombstone then purge
        proc_policy = self.policies.get(MemoryTier.PROCEDURAL)
        if proc_policy:
            for item in list(store.items_by_tier(MemoryTier.PROCEDURAL)):
                if self.is_protected(item):
                    stats["protected_skipped"] += 1
                    continue
                state = self._tombstones.get(item.item_id, TombstoneState.ACTIVE)
                if state == TombstoneState.ACTIVE and proc_policy.should_decay(item, now):
                    self._tombstones[item.item_id] = TombstoneState.GRACE
                    item.metadata["grace_start"] = now
                    stats["tombstoned"] += 1
                elif state == TombstoneState.GRACE:
                    grace_start = item.metadata.get("grace_start", now)
                    if _days_between(grace_start, now) >= proc_policy.grace_days:
                        self._tombstones[item.item_id] = TombstoneState.TOMBSTONED
                        store.remove(item.item_id)
                        stats["purged"] += 1
        return stats

    def simulate(self, store: MemoryStore, start: str, days: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            t = datetime.fromisoformat(start)
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return results
        for day in range(days):
            now = (t + timedelta(days=day)).isoformat()
            stats = self.apply_decay(store, now)
            stats["day"] = day
            stats["total_items"] = store.total_count()
            results.append(stats)
        return results

    def property_protected_never_deleted(self, store: MemoryStore, now: str) -> bool:
        """Invariant check: decay must never remove protected items.

        Any protected item missing after a decay run violates the
        invariant, no matter how it disappeared — the earlier version of
        this check also demanded a tombstone record, which protected
        items never have, so genuine violations slipped through.
        """
        protected_ids = {i.item_id for i in store._items.values() if self.is_protected(i)}
        self.apply_decay(store, now)
        return all(pid in store._items for pid in sorted(protected_ids))


def _days_between(a: str, b: str) -> float:
    try:
        ta = datetime.fromisoformat(a)
        tb = datetime.fromisoformat(b)
        if ta.tzinfo is None:
            ta = ta.replace(tzinfo=UTC)
        if tb.tzinfo is None:
            tb = tb.replace(tzinfo=UTC)
        return (tb - ta).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0
