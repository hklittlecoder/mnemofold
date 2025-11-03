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
    access_boost: float = 0.15
    max_access_boosts: int = 4

    def decay_factor(self, days: float) -> float:
        return math.exp(-days * math.log(2) / self.half_life_days)

    def decayed_salience(self, item: MemoryItem, now: str) -> float:
        age = _age_days(item, now)
        boost_count = min(int(item.metadata.get("access_boost_count", 0)), self.max_access_boosts)
        boosted_half_life = self.half_life_days * (1.0 + boost_count * self.access_boost)
        factor = math.exp(-age * math.log(2) / max(0.01, boosted_half_life))
        return item.salience * factor

    def should_decay(self, item: MemoryItem, now: str) -> bool:
        if item.pinned:
            return False
        age = _age_days(item, now)
        if age > self.max_age_days:
            return True
        return self.decayed_salience(item, now) < self.min_salience

    def record_access(self, item: MemoryItem, now: str) -> None:
        """Bump the access boost counter and reset the last-accessed time."""
        current = int(item.metadata.get("access_boost_count", 0))
        item.metadata["access_boost_count"] = min(current + 1, self.max_access_boosts)
        item.last_accessed = now


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
    _holds: dict[str, str] = field(default_factory=dict)  # item_id -> reason

    def is_protected(self, item: MemoryItem) -> bool:
        if item.pinned:
            return True
        if item.item_id in self._holds:
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

    def place_hold(self, item_id: str, reason: str = "") -> None:
        """Place a legal hold; held items are protected from all decay.

        Holds are keyed by item id and independent of tags, so records
        can be frozen for audits or legal requests without touching the
        items themselves.
        """
        self._holds[item_id] = reason

    def release_hold(self, item_id: str) -> bool:
        """Release a hold. Returns False when no hold existed."""
        return self._holds.pop(item_id, None) is not None

    def note_access(self, store: MemoryStore, item_id: str, now: str) -> bool:
        """Record an access for spaced-repetition style boost.

        Returns True when the item was found and boosted. The boost
        effectively extends half-life, so frequently recalled memories
        survive longer before they decay out of a tier.
        """
        item = store.get(item_id)
        if item is None:
            return False
        policy = self.policies.get(item.tier)
        if policy is None:
            item.last_accessed = now
            return True
        policy.record_access(item, now)
        return True

    def is_on_hold(self, item_id: str) -> bool:
        return item_id in self._holds

    def holds(self) -> dict[str, str]:
        """All active holds as {item_id: reason}, sorted by item id."""
        return dict(sorted(self._holds.items()))

    def snapshot(self, store: MemoryStore, now: str) -> list[dict[str, Any]]:
        """Per-item retention state for audits and reports.

        Rows are sorted by item id and floats are quantized at this
        production point, so equal inputs produce byte-identical
        snapshots across runs and platforms.
        """
        rows: list[dict[str, Any]] = []
        for item_id in sorted(store._items):
            item = store._items[item_id]
            policy = self.policies.get(item.tier)
            decayed = policy.decayed_salience(item, now) if policy is not None else item.salience
            rows.append(
                {
                    "item_id": item_id,
                    "tier": str(item.tier),
                    "age_days": round(_age_days(item, now), 6),
                    "decayed_salience": round(decayed, 6),
                    "protected": self.is_protected(item),
                    "state": str(self._tombstones.get(item_id, TombstoneState.ACTIVE)),
                }
            )
        return rows


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
