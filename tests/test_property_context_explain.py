"""Randomized cross-checks: explanations agree with pack and with brute force.

For small random instances the explained selection must (a) match the
pack's items exactly, (b) reach the brute-force optimal total value, and
(c) never exceed the budget.
"""

import random

from mnemofold.context import (
    ContextItem,
    ContextPacker,
    effective_priority,
    explain_pack,
    knapsack_brute_force,
)


def random_items(seed: int) -> list[ContextItem]:
    rng = random.Random(seed)
    items = []
    for i in range(rng.randint(2, 8)):
        items.append(
            ContextItem(
                item_id=f"i{i}",
                content="content",
                token_estimate=rng.randint(1, 40),
                priority=round(rng.uniform(0.1, 5.0), 3),
            )
        )
    return items


class TestExplainProperties:
    def test_explanation_matches_pack_selection(self):
        for seed in range(25):
            items = random_items(seed)
            packer = ContextPacker(budget=60)
            report = explain_pack(packer, items)
            pack = packer.pack(items)
            explained = {r["item_id"] for r in report["rows"] if r["selected"]}
            assert explained == {it.item_id for it in pack.items}, seed

    def test_selection_reaches_brute_force_optimum(self):
        for seed in range(25):
            items = random_items(seed)
            budget = 60
            values = [effective_priority(it) for it in items]
            best_indices = knapsack_brute_force(items, budget, values=values)
            best_value = sum(values[i] for i in best_indices)
            report = explain_pack(ContextPacker(budget=budget), items)
            chosen_value = sum(r["effective_priority"] for r in report["rows"] if r["selected"])
            assert abs(chosen_value - best_value) < 1e-6, seed

    def test_budget_never_exceeded(self):
        for seed in range(25):
            items = random_items(seed)
            report = explain_pack(ContextPacker(budget=45), items)
            assert report["used"] <= report["budget"], seed
            assert report["headroom"] >= 0, seed

    def test_all_fit_means_all_eligible_selected(self):
        for seed in range(25):
            items = random_items(seed)
            budget = sum(it.token_estimate for it in items)
            report = explain_pack(ContextPacker(budget=budget), items)
            assert all(r["selected"] for r in report["rows"]), seed
