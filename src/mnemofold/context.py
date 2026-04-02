"""Context packs: budgeted selection for LLM context windows.

Implements a deterministic token estimator, 0/1 knapsack with exact DP
and greedy comparator, task-conditioned packing profiles, ordering rules,
and a guarantee that packed context never exceeds the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np


class BudgetExceededError(RuntimeError):
    """Raised when a pack would exceed its token budget.

    The knapsack DP makes this unreachable in normal operation; the
    explicit error (instead of a bare assert, which -O strips) keeps the
    budget invariant enforced in every runtime mode.
    """


class PackingProfile(StrEnum):
    """Task-conditioned packing profiles."""

    TRIAGE = "triage"
    MEETING_PREP = "meeting_prep"
    WEEKLY_REVIEW = "weekly_review"
    STANDUP = "standup"
    GENERAL = "general"


PROFILE_WEIGHTS: dict[PackingProfile, dict[str, float]] = {
    PackingProfile.GENERAL: {"salience": 1.0, "recency": 0.5, "relevance": 0.8},
    PackingProfile.TRIAGE: {"salience": 1.2, "deadline": 1.0, "sender": 0.6},
    PackingProfile.MEETING_PREP: {"relevance": 1.2, "people": 1.0, "decisions": 0.8},
    PackingProfile.WEEKLY_REVIEW: {"recency": 1.0, "commitments": 1.0, "projects": 0.7},
    PackingProfile.STANDUP: {"recency": 1.2, "tasks": 1.0, "blockers": 0.9},
}


@dataclass(slots=True)
class ContextItem:
    """An item eligible for inclusion in a context pack."""

    item_id: str
    content: str
    title: str = ""
    token_estimate: int = 0
    priority: float = 0.0
    category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)
    item_time: str = ""  # ISO instant; drives chronological ordering


@dataclass(slots=True)
class ContextPack:
    """A budgeted context pack."""

    items: list[ContextItem] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    profile: PackingProfile = PackingProfile.GENERAL
    ordering: str = "priority"

    def __len__(self) -> int:
        return len(self.items)

    def to_markdown(self) -> str:
        lines = [
            f"# Context Pack ({self.profile})",
            f"Budget: {self.budget} tokens, Used: {self.total_tokens} tokens",
            "",
        ]
        for i, item in enumerate(self.items, 1):
            lines.append(f"## {i}. {item.title or item.item_id} [{item.token_estimate} tokens]")
            lines.append(f"*Category: {item.category} | Priority: {item.priority:.3f}*")
            lines.append("")
            lines.append(item.content)
            lines.append("")
            lines.append(f"*Source: `{item.item_id}`*")
            lines.append("")
        return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Deterministic token count estimator.

    Uses a simple heuristic: ~4 chars per token for English text.
    This is a rough estimate, not an exact tokenizer, but it's
    deterministic and fast. The budget uses this estimator consistently.
    """
    if not text:
        return 0
    # Rough estimate: chars / 4 + words / 1.3 ≈ tokens
    char_count = len(text)
    word_count = len(text.split())
    return max(1, int((char_count / 4.0 + word_count / 1.3) / 2.0))


def effective_priority(
    item: ContextItem, profile: PackingProfile = PackingProfile.GENERAL
) -> float:
    """Base priority plus the profile-weighted component bonuses.

    Each packing profile names the signals it cares about (see
    PROFILE_WEIGHTS). Component values are read from ``item.metadata``:
    numbers are used as-is, booleans count as 1.0/0.0, and missing or
    non-numeric entries contribute nothing. The result is quantized to
    six decimals at this production point so selection and ordering are
    reproducible across platforms.
    """
    weights = PROFILE_WEIGHTS.get(profile) or PROFILE_WEIGHTS[PackingProfile.GENERAL]
    total = item.priority
    for name in sorted(weights):
        value = item.metadata.get(name)
        if isinstance(value, bool):
            total += weights[name] * (1.0 if value else 0.0)
        elif isinstance(value, (int, float)):
            total += weights[name] * float(value)
    return round(total, 6)


def knapsack_dp(
    items: list[ContextItem], budget: int, values: list[float] | None = None
) -> list[int]:
    """0/1 knapsack exact DP solution. Returns indices of selected items.

    Maximizes total value (item priority by default, or the ``values``
    override when given) subject to total token_estimate <= budget.
    Result is always optimal for integer token counts. Zero-weight
    items always fit, including at a zero budget.
    """
    n = len(items)
    if n == 0 or budget < 0:
        return []

    weights = np.array([it.token_estimate for it in items], dtype=np.int64)
    value_list = values if values is not None else [it.priority for it in items]
    value_array = np.array(value_list, dtype=np.float64)

    # DP table: dp[w] = max value achievable with weight w
    dp = np.zeros(budget + 1, dtype=np.float64)
    selected = np.zeros((n, budget + 1), dtype=bool)

    for i in range(n):
        w = weights[i]
        v = value_array[i]
        if w > budget:
            continue
        # Iterate backwards to avoid reusing items
        for j in range(budget, w - 1, -1):
            candidate = dp[j - w] + v
            if candidate > dp[j]:
                dp[j] = candidate
                selected[i][j] = True

    # Backtrack to find selected items
    result: list[int] = []
    w = budget
    for i in range(n - 1, -1, -1):
        if selected[i][w]:
            result.append(i)
            w -= weights[i]
    result.reverse()
    return result


def knapsack_greedy(items: list[ContextItem], budget: int) -> list[int]:
    """Greedy knapsack approximation (by priority/token ratio).

    Used as a comparator for the DP solution. On small instances the DP
    solution should always be >= the greedy solution.
    """
    if not items or budget < 0:
        return []
    # Sort by priority per token (descending)
    indexed = [(i, it.priority / max(1, it.token_estimate)) for i, it in enumerate(items)]
    indexed.sort(key=lambda x: x[1], reverse=True)
    used = 0
    selected: list[int] = []
    for idx, _ in indexed:
        w = items[idx].token_estimate
        if used + w <= budget:
            selected.append(idx)
            used += w
    return sorted(selected)


def knapsack_brute_force(
    items: list[ContextItem], budget: int, values: list[float] | None = None
) -> list[int]:
    """Exhaustive reference solver for small instances (2^n subsets).

    Enumerates every subset and keeps the feasible one with maximum
    total value (``item.priority`` by default, or the ``values``
    override — matching :func:`knapsack_dp`). Ties break toward the
    lexicographically smallest index tuple, so the answer itself is
    deterministic. Exponential on purpose: tests use it on handfuls of
    items to prove the DP solver optimal.
    """
    n = len(items)
    if n == 0 or budget < 0:
        return []
    value_list = values if values is not None else [it.priority for it in items]
    best_value = 0.0
    best: tuple[int, ...] = ()
    for mask in range(1 << n):
        total_weight = 0
        total_value = 0.0
        chosen: list[int] = []
        feasible = True
        for i in range(n):
            if (mask >> i) & 1:
                total_weight += items[i].token_estimate
                if total_weight > budget:
                    feasible = False
                    break
                total_value += value_list[i]
                chosen.append(i)
        if not feasible:
            continue
        if total_value > best_value or (total_value == best_value and tuple(chosen) < best):
            best_value = total_value
            best = tuple(chosen)
    return list(best)


@dataclass
class ContextPacker:
    """Packs items into a budgeted context pack."""

    budget: int = 4096
    profile: PackingProfile = PackingProfile.GENERAL
    ordering: str = "priority"  # priority, chronological, category_grouped

    def pack(self, items: list[ContextItem]) -> ContextPack:
        """Pack items into a context pack respecting the budget.

        Uses exact 0/1 knapsack DP for optimal selection.
        Never exceeds the token budget.
        """
        # Filter items with zero tokens or that are bigger than budget
        eligible = [it for it in items if 0 < it.token_estimate <= self.budget]
        if not eligible:
            return ContextPack(
                items=[],
                total_tokens=0,
                budget=self.budget,
                profile=self.profile,
                ordering=self.ordering,
            )

        values = [effective_priority(it, self.profile) for it in eligible]
        selected_indices = knapsack_dp(eligible, self.budget, values=values)
        selected_items = [eligible[i] for i in selected_indices]

        # Order the selected items
        selected_items = self._order(selected_items)

        total = sum(it.token_estimate for it in selected_items)
        if total > self.budget:
            raise BudgetExceededError(f"Budget exceeded: {total} > {self.budget}")

        return ContextPack(
            items=selected_items,
            total_tokens=total,
            budget=self.budget,
            profile=self.profile,
            ordering=self.ordering,
        )

    def _order(self, items: list[ContextItem]) -> list[ContextItem]:
        if self.ordering == "priority":
            return sorted(items, key=lambda it: effective_priority(it, self.profile), reverse=True)
        if self.ordering == "category_grouped":
            # Group by category, within each category sort by priority
            by_cat: dict[str, list[ContextItem]] = {}
            for it in items:
                by_cat.setdefault(it.category, []).append(it)
            result: list[ContextItem] = []
            for cat in sorted(by_cat.keys()):
                result.extend(
                    sorted(
                        by_cat[cat],
                        key=lambda it: effective_priority(it, self.profile),
                        reverse=True,
                    )
                )
            return result
        if self.ordering == "chronological":
            return sorted(items, key=_chrono_key)
        # default: priority order
        return sorted(items, key=lambda it: effective_priority(it, self.profile), reverse=True)


def _chrono_key(item: ContextItem) -> tuple[int, float, str]:
    """Sort key for chronological ordering.

    Compares true instants (offset-aware), not ISO strings: items with
    undated or unparseable ``item_time`` sort last, and ids break ties
    deterministically.
    """
    if item.item_time:
        try:
            parsed: datetime | None = datetime.fromisoformat(item.item_time)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return (0, parsed.timestamp(), item.item_id)
    return (1, 0.0, item.item_id)


def verify_budget(pack: ContextPack) -> bool:
    """Property check: pack never exceeds its budget."""
    total = sum(it.token_estimate for it in pack.items)
    return total <= pack.budget


def verify_dp_vs_greedy(items: list[ContextItem], budget: int) -> bool:
    """Property check: DP solution is at least as good as greedy."""
    if not items or budget < 0:
        return True
    dp_indices = knapsack_dp(items, budget)
    greedy_indices = knapsack_greedy(items, budget)
    dp_value = sum(items[i].priority for i in dp_indices)
    greedy_value = sum(items[i].priority for i in greedy_indices)
    return dp_value >= greedy_value - 1e-9


def explain_pack(packer: ContextPacker, items: list[ContextItem]) -> dict[str, Any]:
    """Per-candidate rationale for one packing decision.

    Runs the same exact-knapsack selection as :meth:`ContextPacker.pack`
    and reports every candidate in INPUT order with its effective
    priority, value density (priority per token) and outcome:

    * ``selected`` — part of the optimal subset;
    * ``ineligible`` — zero tokens or larger than the whole budget;
    * ``outcompeted`` — eligible, but the exact solver found a
      higher-value feasible subset without it.

    ``outcompeted`` deliberately does NOT mean "low density": the
    knapsack optimum can skip a dense item when a combination of others
    fits the budget better. Totals reconcile with the pack itself
    (``used`` equals the selected token sum and never exceeds budget).
    """
    pack = packer.pack(items)
    selected_ids = {it.item_id for it in pack.items}
    rows: list[dict[str, Any]] = []
    for item in items:
        effective = effective_priority(item, packer.profile)
        if item.item_id in selected_ids:
            reason = "selected"
        elif not 0 < item.token_estimate <= packer.budget:
            reason = "ineligible"
        else:
            reason = "outcompeted"
        rows.append(
            {
                "item_id": item.item_id,
                "tokens": item.token_estimate,
                "effective_priority": effective,
                "value_density": (
                    round(effective / item.token_estimate, 6) if item.token_estimate > 0 else 0.0
                ),
                "selected": reason == "selected",
                "reason": reason,
            }
        )
    return {
        "budget": pack.budget,
        "used": pack.total_tokens,
        "headroom": pack.budget - pack.total_tokens,
        "ordering": pack.ordering,
        "rows": rows,
    }
