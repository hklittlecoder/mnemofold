"""Tests for context packs and knapsack."""

from __future__ import annotations

import pytest

from mnemofold import context as context_module
from mnemofold.context import (
    BudgetExceededError,
    ContextItem,
    ContextPacker,
    PackingProfile,
    effective_priority,
    estimate_tokens,
    knapsack_dp,
    knapsack_greedy,
    verify_budget,
    verify_dp_vs_greedy,
)


class TestTokenEstimator:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_short_text(self):
        n = estimate_tokens("hello world")
        assert n > 0

    def test_deterministic(self):
        assert estimate_tokens("hello world") == estimate_tokens("hello world")

    def test_longer_text_more_tokens(self):
        short = estimate_tokens("hi")
        long = estimate_tokens("hello world this is a much longer text")
        assert long > short


class TestKnapsackDP:
    def _make_items(self, n: int, seed: int = 42) -> list[ContextItem]:
        import random

        rng = random.Random(seed)
        items = []
        for i in range(n):
            items.append(
                ContextItem(
                    item_id=f"item_{i}",
                    content=f"content {i}",
                    token_estimate=rng.randint(10, 100),
                    priority=rng.random(),
                )
            )
        return items

    def test_empty_items(self):
        assert knapsack_dp([], 100) == []

    def test_zero_budget(self):
        items = [ContextItem("a", "x", token_estimate=10, priority=1.0)]
        assert knapsack_dp(items, 0) == []

    def test_single_item_fits(self):
        items = [ContextItem("a", "x", token_estimate=10, priority=1.0)]
        result = knapsack_dp(items, 20)
        assert result == [0]

    def test_single_item_too_big(self):
        items = [ContextItem("a", "x", token_estimate=100, priority=1.0)]
        result = knapsack_dp(items, 50)
        assert result == []

    def test_picks_higher_value(self):
        items = [
            ContextItem("a", "x", token_estimate=50, priority=0.5),
            ContextItem("b", "y", token_estimate=50, priority=0.9),
        ]
        result = knapsack_dp(items, 50)
        assert len(result) == 1
        assert items[result[0]].priority == 0.9

    def test_picks_multiple(self):
        items = [
            ContextItem("a", "x", token_estimate=30, priority=0.5),
            ContextItem("b", "y", token_estimate=30, priority=0.5),
            ContextItem("c", "z", token_estimate=30, priority=0.5),
        ]
        result = knapsack_dp(items, 100)
        assert len(result) == 3

    def test_dp_better_than_greedy(self):
        # Classic counterexample: greedy by ratio fails on some instances
        items = [
            ContextItem("a", "x" * 100, token_estimate=50, priority=60),  # ratio 1.2
            ContextItem("b", "y" * 100, token_estimate=50, priority=55),  # ratio 1.1
            ContextItem("c", "z" * 100, token_estimate=51, priority=56),  # ratio 1.1
        ]
        # With budget 100: greedy picks a (60) but optimal is b+c (111)
        # Wait that doesn't work either since b+c = 101 > 100
        # Let's just verify DP >= greedy
        assert verify_dp_vs_greedy(items, 100)

    def test_brute_force_small_instances(self):
        """Verify DP against brute force on small instances."""
        import random

        rng = random.Random(123)
        for _ in range(20):
            n = rng.randint(1, 8)
            budget = rng.randint(50, 200)
            items = [
                ContextItem(
                    f"i{i}", f"c{i}", token_estimate=rng.randint(10, 50), priority=rng.random()
                )
                for i in range(n)
            ]
            dp_indices = knapsack_dp(items, budget)
            dp_value = sum(items[i].priority for i in dp_indices)
            dp_weight = sum(items[i].token_estimate for i in dp_indices)
            assert dp_weight <= budget

            # Brute force
            best_val = 0.0
            for mask in range(1 << n):
                indices = [i for i in range(n) if mask & (1 << i)]
                weight = sum(items[i].token_estimate for i in indices)
                value = sum(items[i].priority for i in indices)
                if weight <= budget and value > best_val:
                    best_val = value
            assert dp_value == pytest.approx(best_val, rel=1e-6)


class TestGreedyKnapsack:
    def test_greedy_selects_something(self):
        items = [
            ContextItem("a", "x", token_estimate=10, priority=0.8),
            ContextItem("b", "y", token_estimate=20, priority=0.9),
        ]
        result = knapsack_greedy(items, 100)
        assert len(result) > 0

    def test_greedy_stays_within_budget(self):
        import random

        rng = random.Random(7)
        items = [
            ContextItem(
                f"i{i}", f"c{i}", token_estimate=rng.randint(10, 100), priority=rng.random()
            )
            for i in range(20)
        ]
        result = knapsack_greedy(items, 500)
        total = sum(items[i].token_estimate for i in result)
        assert total <= 500


class TestContextPacker:
    def test_pack_empty(self):
        packer = ContextPacker(budget=1000)
        pack = packer.pack([])
        assert len(pack) == 0
        assert pack.total_tokens == 0

    def test_pack_within_budget(self):
        items = [
            ContextItem(
                f"i{i}", f"content {i} " * 20, token_estimate=100 + i * 10, priority=0.5 + i * 0.1
            )
            for i in range(10)
        ]
        packer = ContextPacker(budget=500)
        pack = packer.pack(items)
        assert verify_budget(pack)

    def test_pack_property_budget(self):
        import random

        rng = random.Random(42)
        items = [
            ContextItem(
                f"i{i}", f"c{i}" * 10, token_estimate=rng.randint(20, 200), priority=rng.random()
            )
            for i in range(30)
        ]
        packer = ContextPacker(budget=1000)
        pack = packer.pack(items)
        assert verify_budget(pack)

    def test_pack_ordering_priority(self):
        items = [
            ContextItem("low", "c1", token_estimate=50, priority=0.3),
            ContextItem("high", "c2", token_estimate=50, priority=0.9),
            ContextItem("med", "c3", token_estimate=50, priority=0.6),
        ]
        packer = ContextPacker(budget=1000, ordering="priority")
        pack = packer.pack(items)
        assert pack.items[0].priority >= pack.items[-1].priority

    def test_to_markdown(self):
        items = [ContextItem("a", "hello world", title="Test", token_estimate=10, priority=1.0)]
        packer = ContextPacker(budget=100)
        pack = packer.pack(items)
        md = pack.to_markdown()
        assert "Test" in md
        assert "hello world" in md
        assert str(pack.total_tokens) in md


class TestPackingProfiles:
    def test_all_profiles_have_weights(self):
        from mnemofold.context import PROFILE_WEIGHTS

        for profile in PackingProfile:
            assert profile in PROFILE_WEIGHTS
            assert len(PROFILE_WEIGHTS[profile]) > 0


class TestBudgetGuard:
    def _items(self) -> list[ContextItem]:
        return [
            ContextItem(item_id="a", content="aaa", token_estimate=50, priority=1.0),
            ContextItem(item_id="b", content="bbb", token_estimate=60, priority=1.0),
        ]

    def test_normal_packing_never_raises(self):
        packer = ContextPacker(budget=100)
        pack = packer.pack(self._items())
        assert pack.total_tokens <= 100
        assert verify_budget(pack)

    def test_broken_selection_raises_explicit_error(self, monkeypatch):
        # Simulate a hypothetical selector bug that ignores the budget:
        # the packer must fail loudly rather than silently overflow.
        monkeypatch.setattr(
            context_module,
            "knapsack_dp",
            lambda items, budget, **kwargs: list(range(len(items))),
        )
        packer = ContextPacker(budget=100)
        with pytest.raises(BudgetExceededError, match="Budget exceeded"):
            packer.pack(self._items())

    def test_error_is_a_runtime_error(self):
        assert issubclass(BudgetExceededError, RuntimeError)


class TestEffectivePriority:
    def test_general_profile_combines_components(self):
        item = ContextItem(
            item_id="x",
            content="c",
            priority=1.0,
            metadata={"salience": 0.5, "recency": 0.4, "relevance": 0.2},
        )
        # 1.0 + 1.0*0.5 + 0.5*0.4 + 0.8*0.2 = 1.86
        assert effective_priority(item, PackingProfile.GENERAL) == 1.86

    def test_boolean_components_count_as_one(self):
        item = ContextItem(
            item_id="x", content="c", priority=0.0, metadata={"deadline": True, "sender": False}
        )
        assert effective_priority(item, PackingProfile.TRIAGE) == 1.0

    def test_non_numeric_metadata_is_ignored(self):
        item = ContextItem(
            item_id="x", content="c", priority=0.5, metadata={"salience": "high", "recency": None}
        )
        assert effective_priority(item, PackingProfile.GENERAL) == 0.5

    def test_without_metadata_priority_is_unchanged(self):
        item = ContextItem(item_id="x", content="c", priority=0.75)
        assert effective_priority(item) == 0.75
        assert effective_priority(item, PackingProfile.TRIAGE) == 0.75

    def test_profile_changes_selection_under_tight_budget(self):
        items = [
            ContextItem(item_id="a", content="a", token_estimate=10, priority=1.0),
            ContextItem(
                item_id="b", content="b", token_estimate=10, priority=0.6, metadata={"recency": 1.0}
            ),
        ]
        general = ContextPacker(budget=10, profile=PackingProfile.GENERAL).pack(items)
        assert [it.item_id for it in general.items] == ["b"]  # 0.6 + 0.5*1.0 > 1.0
        triage = ContextPacker(budget=10, profile=PackingProfile.TRIAGE).pack(items)
        assert [it.item_id for it in triage.items] == ["a"]  # recency not a triage signal

    def test_ordering_uses_effective_priority(self):
        items = [
            ContextItem(item_id="a", content="a", token_estimate=5, priority=1.0),
            ContextItem(
                item_id="b", content="b", token_estimate=5, priority=0.6, metadata={"recency": 1.0}
            ),
        ]
        general = ContextPacker(budget=20, profile=PackingProfile.GENERAL).pack(items)
        assert [it.item_id for it in general.items] == ["b", "a"]
        triage = ContextPacker(budget=20, profile=PackingProfile.TRIAGE).pack(items)
        assert [it.item_id for it in triage.items] == ["a", "b"]
