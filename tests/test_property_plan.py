"""Property tests: plan DAG validation versus execution order.

For any seeded random DAG, validation must pass, the topological order
must respect every dependency, and the perceive-plan-act-observe loop
must complete each step exactly once with all dependencies already
done. Malformed plans (cycles, dangling references) must be rejected
by validation and yield incomplete orders.
"""

from __future__ import annotations

import random

import pytest

from mnemofold.plan import Plan, PlanLoop, PlanStep, topological_order, validate_plan
from mnemofold.tools import ToolRegistry


def _random_dag(rng: random.Random, n: int) -> Plan:
    """Random acyclic plan: dependencies only point at lower-numbered steps."""
    steps = []
    for i in range(n):
        deps = [f"s{j}" for j in range(i) if rng.random() < 0.3]
        steps.append(PlanStep(step_id=f"s{i}", name=f"step {i}", depends_on=deps))
    rng.shuffle(steps)
    return Plan(plan_id="p-random", name="random dag", steps=steps)


class TestDagValidationMatchesExecution:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_topological_order_respects_every_dependency(self, seed):
        plan = _random_dag(random.Random(seed), 8)
        assert validate_plan(plan).valid
        order = topological_order(plan)
        assert sorted(order) == sorted(s.step_id for s in plan.steps)
        position = {sid: idx for idx, sid in enumerate(order)}
        for step in plan.steps:
            for dep in step.depends_on:
                assert position[dep] < position[step.step_id]

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_execution_completes_each_step_once_after_deps(self, seed):
        plan = _random_dag(random.Random(seed + 10), 8)
        outcomes = PlanLoop(plan=plan).run_to_completion(ToolRegistry())
        completed = [o.step_id for o in outcomes if o.status == "completed"]
        assert sorted(completed) == sorted(s.step_id for s in plan.steps)
        seen: set[str] = set()
        for outcome in outcomes:
            step = next(s for s in plan.steps if s.step_id == outcome.step_id)
            assert set(step.depends_on) <= seen
            seen.add(outcome.step_id)

    def test_cycle_is_rejected_and_unrunnable(self):
        plan = Plan(
            plan_id="p-cycle",
            name="cycle",
            steps=[
                PlanStep(step_id="a", name="a", depends_on=["b"]),
                PlanStep(step_id="b", name="b", depends_on=["a"]),
            ],
        )
        result = validate_plan(plan)
        assert not result.valid
        assert len(topological_order(plan)) < 2

    def test_dangling_dependency_is_rejected(self):
        plan = Plan(
            plan_id="p-dangle",
            name="dangle",
            steps=[PlanStep(step_id="a", name="a", depends_on=["ghost"])],
        )
        assert not validate_plan(plan).valid
        assert topological_order(plan) == []
