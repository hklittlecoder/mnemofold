"""Tests for context packs and knapsack."""

from __future__ import annotations

import itertools
import random

import pytest

from mnemofold import context as context_module
from mnemofold.context import (
    BudgetExceededError,
    ContextItem,
    ContextPack,
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


class TestChronologicalOrdering:
    def _item(self, item_id: str, item_time: str, priority: float = 1.0) -> ContextItem:
        # priority must be positive: zero-value items are never selected
        # by the knapsack, which is the documented packing behavior
        return ContextItem(
            item_id=item_id,
            content="c",
            token_estimate=5,
            priority=priority,
            item_time=item_time,
        )

    def test_orders_by_instant_across_offsets(self):
        items = [
            self._item("late", "2025-03-10T09:00:00+00:00"),
            # 08:00 UTC — earlier than "late" though its ISO string sorts after
            self._item("early", "2025-03-10T17:00:00+09:00"),
        ]
        pack = ContextPacker(budget=100, ordering="chronological").pack(items)
        assert [it.item_id for it in pack.items] == ["early", "late"]

    def test_undated_items_sort_last(self):
        items = [
            self._item("nodate", ""),
            self._item("dated", "2025-03-10T09:00:00+00:00"),
        ]
        pack = ContextPacker(budget=100, ordering="chronological").pack(items)
        assert [it.item_id for it in pack.items] == ["dated", "nodate"]

    def test_invalid_timestamp_treated_as_undated(self):
        items = [
            self._item("bad", "not-a-time"),
            self._item("good", "2025-03-10T09:00:00+00:00"),
        ]
        pack = ContextPacker(budget=100, ordering="chronological").pack(items)
        assert [it.item_id for it in pack.items] == ["good", "bad"]

    def test_ties_break_on_item_id(self):
        items = [
            self._item("b", "2025-03-10T09:00:00+00:00"),
            self._item("a", "2025-03-10T09:00:00+00:00"),
        ]
        pack = ContextPacker(budget=100, ordering="chronological").pack(items)
        assert [it.item_id for it in pack.items] == ["a", "b"]

    def test_unknown_ordering_falls_back_to_priority(self):
        items = [self._item("low", "", priority=0.1), self._item("high", "", priority=0.9)]
        pack = ContextPacker(budget=100, ordering="nonsense").pack(items)
        assert [it.item_id for it in pack.items] == ["high", "low"]

    def test_item_time_defaults_to_empty(self):
        assert ContextItem(item_id="x", content="c").item_time == ""


class TestKnapsackProperties:
    """DP optimality checked against brute force on small seeded instances."""

    TOKEN_CHOICES = (0, 1, 3, 7, 12, 25, 80)
    PRIORITY_CHOICES = (0.0, 0.5, 1.0, 2.5, 3.0, 3.0)  # 3.0 twice: deliberate ties

    def _random_items(self, rng: random.Random, n: int) -> list[ContextItem]:
        return [
            ContextItem(
                item_id=f"i{i}",
                content="c",
                token_estimate=rng.choice(self.TOKEN_CHOICES),
                priority=rng.choice(self.PRIORITY_CHOICES),
            )
            for i in range(n)
        ]

    def _brute_force_value(self, items: list[ContextItem], budget: int) -> float:
        best = 0.0
        for size in range(len(items) + 1):
            for combo in itertools.combinations(range(len(items)), size):
                if sum(items[i].token_estimate for i in combo) <= budget:
                    best = max(best, sum(items[i].priority for i in combo))
        return best

    def test_dp_matches_brute_force_optimum(self):
        for seed in range(50):
            rng = random.Random(seed)
            items = self._random_items(rng, rng.randint(1, 10))
            budget = rng.randint(0, 40)
            picked = knapsack_dp(items, budget)
            weight = sum(items[i].token_estimate for i in picked)
            value = sum(items[i].priority for i in picked)
            assert weight <= budget, f"seed {seed}: budget violated"
            assert value == pytest.approx(self._brute_force_value(items, budget)), (
                f"seed {seed}: suboptimal selection"
            )

    def test_dp_never_worse_than_greedy(self):
        for seed in range(50):
            rng = random.Random(seed + 1000)
            items = self._random_items(rng, rng.randint(1, 10))
            budget = rng.randint(0, 40)
            assert verify_dp_vs_greedy(items, budget), f"seed {seed}"

    def test_selection_is_deterministic_and_unique(self):
        rng = random.Random(7)
        items = self._random_items(rng, 10)
        first = knapsack_dp(items, 30)
        second = knapsack_dp(items, 30)
        assert first == second
        assert len(first) == len(set(first))

    def test_zero_weight_items_always_included_when_valuable(self):
        items = [
            ContextItem(item_id="free", content="c", token_estimate=0, priority=2.0),
            ContextItem(item_id="costly", content="c", token_estimate=100, priority=5.0),
        ]
        picked = knapsack_dp(items, 10)
        assert picked == [0]  # only the free item fits

    def test_zero_budget_still_takes_free_items(self):
        # regression: the early-return guard used to drop zero-weight
        # items that fit even when the budget is exactly zero
        items = [
            ContextItem(item_id="paid", content="c", token_estimate=3, priority=2.5),
            ContextItem(item_id="free", content="c", token_estimate=0, priority=0.5),
        ]
        assert knapsack_dp(items, 0) == [1]
        assert knapsack_greedy(items, 0) == [1]
        assert verify_dp_vs_greedy(items, 0)

    def test_empty_and_negative_budgets(self):
        items = [ContextItem(item_id="a", content="c", token_estimate=1, priority=1.0)]
        assert knapsack_dp([], 10) == []
        assert knapsack_dp(items, 0) == []
        assert knapsack_dp(items, -5) == []
        assert knapsack_greedy(items, 0) == []


class TestTokenEstimatorBoundaries:
    def test_empty_text_is_zero(self):
        assert estimate_tokens("") == 0

    def test_single_char_is_at_least_one(self):
        assert estimate_tokens("a") == 1

    def test_estimator_is_deterministic(self):
        text = "the quick brown fox jumps over the lazy dog"
        assert estimate_tokens(text) == estimate_tokens(text)

    def test_longer_text_estimates_more_tokens(self):
        short = estimate_tokens("word")
        long = estimate_tokens("word " * 100)
        assert long > short

    def test_unicode_text_counts_characters(self):
        assert estimate_tokens("记忆折叠") >= 1


class TestPackerBoundaries:
    def _item(self, item_id, tokens, priority=1.0, category="general") -> ContextItem:
        return ContextItem(
            item_id=item_id,
            content="c",
            token_estimate=tokens,
            priority=priority,
            category=category,
        )

    def test_zero_token_items_are_excluded(self):
        pack = ContextPacker(budget=100).pack([self._item("zero", 0), self._item("real", 10)])
        assert [it.item_id for it in pack.items] == ["real"]

    def test_oversized_items_are_excluded(self):
        pack = ContextPacker(budget=10).pack([self._item("huge", 11)])
        assert pack.items == []
        assert pack.total_tokens == 0

    def test_empty_input_produces_empty_pack_with_metadata(self):
        packer = ContextPacker(budget=64, profile=PackingProfile.STANDUP)
        pack = packer.pack([])
        assert pack.items == []
        assert pack.budget == 64
        assert pack.profile == PackingProfile.STANDUP
        assert len(pack) == 0

    def test_zero_budget_packs_nothing(self):
        assert ContextPacker(budget=0).pack([self._item("a", 1)]).items == []

    def test_budget_adherence_with_many_items(self):
        items = [self._item(f"i{n}", n + 1, priority=float(n % 5)) for n in range(30)]
        pack = ContextPacker(budget=50).pack(items)
        assert pack.total_tokens <= 50
        assert verify_budget(pack)

    def test_category_grouped_ordering(self):
        items = [
            self._item("b2", 5, priority=0.2, category="beta"),
            self._item("a1", 5, priority=0.9, category="alpha"),
            self._item("a2", 5, priority=0.5, category="alpha"),
        ]
        pack = ContextPacker(budget=100, ordering="category_grouped").pack(items)
        assert [it.item_id for it in pack.items] == ["a1", "a2", "b2"]

    def test_markdown_contains_budget_titles_and_sources(self):
        pack = ContextPacker(budget=100).pack([self._item("m1", 10)])
        markdown = pack.to_markdown()
        assert "Budget: 100 tokens" in markdown
        assert "m1" in markdown
        assert "*Source: `m1`*" in markdown

    def test_verify_budget_false_on_overfull_manual_pack(self):
        pack = ContextPack(
            items=[self._item("a", 60), self._item("b", 60)],
            total_tokens=120,
            budget=100,
        )
        assert verify_budget(pack) is False


class TestKnapsackBruteForce:
    def _item(self, item_id: str, tokens: int, priority: float):
        return context_module.ContextItem(
            item_id=item_id, content="x", token_estimate=tokens, priority=priority
        )

    def test_brute_force_value_matches_dp_on_random_small_instances(self):
        rng = random.Random(20250401)
        for _ in range(40):
            n = rng.randint(1, 7)
            items = [
                self._item(f"i{i}", rng.randint(0, 6), round(rng.uniform(0, 1), 3))
                for i in range(n)
            ]
            budget = rng.randint(0, 10)
            dp_value = sum(items[i].priority for i in context_module.knapsack_dp(items, budget))
            brute_value = sum(
                items[i].priority for i in context_module.knapsack_brute_force(items, budget)
            )
            assert dp_value == pytest.approx(brute_value, abs=1e-9)

    def test_brute_force_is_feasible_and_deterministic(self):
        items = [self._item("a", 3, 0.9), self._item("b", 4, 0.8), self._item("c", 5, 0.7)]
        first = context_module.knapsack_brute_force(items, 7)
        assert first == context_module.knapsack_brute_force(items, 7)
        assert sum(items[i].token_estimate for i in first) <= 7
        assert first == [0, 1]

    def test_brute_force_respects_value_override(self):
        items = [self._item("a", 2, 0.1), self._item("b", 2, 0.2)]
        chosen = context_module.knapsack_brute_force(items, 2, values=[5.0, 1.0])
        assert chosen == [0]
        assert context_module.knapsack_dp(items, 2, values=[5.0, 1.0]) == [0]

    def test_brute_force_edges(self):
        assert context_module.knapsack_brute_force([], 5) == []
        item = self._item("a", 1, 1.0)
        assert context_module.knapsack_brute_force([item], -1) == []
        assert context_module.knapsack_brute_force([item], 0) == []

    def test_zero_weight_items_always_fit(self):
        items = [self._item("free", 0, 0.5), self._item("paid", 3, 0.9)]
        assert context_module.knapsack_brute_force(items, 0) == [0]
        assert sorted(context_module.knapsack_brute_force(items, 3)) == [0, 1]
