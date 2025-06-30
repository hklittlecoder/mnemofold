"""Plan DSL and execution loop.

Versioned JSON plan schema with steps, typed inputs/outputs,
preconditions/effects, dependency DAG validation, topological planner,
and a perceive-plan-act-observe loop with budgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PlanStatus(StrEnum):
    DRAFT = "draft"
    VALID = "valid"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class PlanStep:
    step_id: str
    name: str
    tool: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    effects: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    budget_tokens: int = 0
    status: str = "pending"  # pending, running, completed, failed, skipped


@dataclass
class Plan:
    plan_id: str
    name: str
    version: int = 1
    status: PlanStatus = PlanStatus.DRAFT
    steps: list[PlanStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    total_budget_tokens: int = 100000
    token_used: int = 0
    step_budget: int = 100

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = PlanStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "version": self.version,
            "status": str(self.status),
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "tool": s.tool,
                    "inputs": s.inputs,
                    "outputs": list(s.outputs),
                    "preconditions": list(s.preconditions),
                    "effects": list(s.effects),
                    "depends_on": list(s.depends_on),
                    "status": s.status,
                }
                for s in self.steps
            ],
            "total_budget_tokens": self.total_budget_tokens,
            "step_budget": self.step_budget,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        plan = cls(
            plan_id=d["plan_id"],
            name=d["name"],
            version=d.get("version", 1),
            status=d.get("status", PlanStatus.DRAFT),
            total_budget_tokens=d.get("total_budget_tokens", 100000),
            step_budget=d.get("step_budget", 100),
            metadata=d.get("metadata", {}),
        )
        for sd in d.get("steps", []):
            plan.steps.append(
                PlanStep(
                    step_id=sd["step_id"],
                    name=sd["name"],
                    tool=sd.get("tool", ""),
                    inputs=sd.get("inputs", {}),
                    outputs=sd.get("outputs", []),
                    preconditions=sd.get("preconditions", []),
                    effects=sd.get("effects", []),
                    depends_on=sd.get("depends_on", []),
                    status=sd.get("status", "pending"),
                )
            )
        return plan


@dataclass
class PlanValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _reference_parts(value: Any) -> tuple[str, str] | None:
    """Split a ``$step_id.output`` reference; None for plain literals."""
    if not isinstance(value, str) or not value.startswith("$"):
        return None
    body = value[1:]
    step_id, _, output = body.partition(".")
    return step_id, output


def validate_plan(plan: Plan) -> PlanValidationResult:
    """Validate a plan: DAG shape, references, and budget sanity.

    Checks for cycles, dangling depends_on references, malformed typed
    input references (``$step.output`` must name a known step and one of
    its declared outputs), and budget sanity.
    """
    result = PlanValidationResult(valid=True)

    step_ids = {s.step_id for s in plan.steps}

    # Check dangling depends_on
    for step in plan.steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                result.errors.append(f"step '{step.step_id}': depends on unknown step '{dep}'")
                result.valid = False
            if dep == step.step_id:
                result.errors.append(f"step '{step.step_id}': depends on itself")
                result.valid = False

    # Check typed input references ($step.output)
    outputs_by_step = {s.step_id: set(s.outputs) for s in plan.steps}
    for step in plan.steps:
        for input_name, value in step.inputs.items():
            ref = _reference_parts(value)
            if ref is None:
                continue
            ref_step, ref_output = ref
            if ref_step == step.step_id:
                result.errors.append(
                    f"step '{step.step_id}': input '{input_name}' references itself"
                )
                result.valid = False
            elif ref_step not in step_ids:
                result.errors.append(
                    f"step '{step.step_id}': input '{input_name}' references "
                    f"unknown step '{ref_step}'"
                )
                result.valid = False
            elif ref_output not in outputs_by_step.get(ref_step, set()):
                result.errors.append(
                    f"step '{step.step_id}': input '{input_name}' references "
                    f"undeclared output '{ref_output}' of step '{ref_step}'"
                )
                result.valid = False

    # Check for cycles via DFS
    if result.valid:
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(sid: str) -> bool:
            visited.add(sid)
            stack.add(sid)
            step = next(s for s in plan.steps if s.step_id == sid)
            for dep in step.depends_on:
                if dep in stack:
                    return False
                if dep not in visited and not dfs(dep):
                    return False
            stack.discard(sid)
            return True

        for step in plan.steps:
            if step.step_id not in visited and not dfs(step.step_id):
                result.errors.append("cycle detected in dependency graph")
                result.valid = False
                break

    # Budget sanity
    total_step_budget = sum(s.budget_tokens for s in plan.steps if s.budget_tokens > 0)
    if total_step_budget > plan.total_budget_tokens:
        result.warnings.append(
            f"sum of step budgets ({total_step_budget}) exceeds total budget ({plan.total_budget_tokens})"
        )

    return result


def topological_order(plan: Plan) -> list[str]:
    """Return step IDs in topological order (dependencies first)."""
    in_degree = {s.step_id: len(s.depends_on) for s in plan.steps}
    adj: dict[str, list[str]] = {s.step_id: [] for s in plan.steps}
    for step in plan.steps:
        for dep in step.depends_on:
            if dep in adj:
                adj[dep].append(step.step_id)

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    result: list[str] = []
    while queue:
        # Sort for deterministic ordering
        queue.sort()
        sid = queue.pop(0)
        result.append(sid)
        for nxt in adj.get(sid, []):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    return result


@dataclass
class PlanLoop:
    """Perceive-plan-act-observe loop with step and token budgets."""

    plan: Plan
    current_step_index: int = 0
    iteration: int = 0
    max_iterations: int = 100

    def can_continue(self) -> bool:
        if self.plan.token_used >= self.plan.total_budget_tokens:
            return False
        if self.iteration >= self.max_iterations:
            return False
        return self.plan.status not in {
            PlanStatus.COMPLETED,
            PlanStatus.FAILED,
            PlanStatus.CANCELLED,
        }

    def steps_completed(self) -> int:
        return sum(1 for s in self.plan.steps if s.status == "completed")

    def steps_failed(self) -> int:
        return sum(1 for s in self.plan.steps if s.status == "failed")


# --- Plan diffing --------------------------------------------------------------


@dataclass(slots=True)
class StepChange:
    """Field-level changes to one step shared by two plan revisions."""

    step_id: str
    fields: dict[str, tuple[Any, Any]]  # field name -> (old, new)


@dataclass(slots=True)
class PlanDiff:
    """Deterministic diff between two plan revisions."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[StepChange] = field(default_factory=list)
    budget_changed: bool = False
    name_changed: bool = False

    def is_empty(self) -> bool:
        return not (
            self.added or self.removed or self.changed or self.budget_changed or self.name_changed
        )


_DIFF_FIELDS = (
    "name",
    "tool",
    "inputs",
    "outputs",
    "preconditions",
    "effects",
    "depends_on",
    "budget_tokens",
)


def diff_plans(old: Plan, new: Plan) -> PlanDiff:
    """Compare two plans step by step.

    Step identity is ``step_id``. Added/removed ids are sorted; changed
    steps are reported in id order with per-field (old, new) pairs so a
    reviewer sees exactly what moved. Plan-level budget and name changes
    are flagged separately.
    """
    old_steps = {s.step_id: s for s in old.steps}
    new_steps = {s.step_id: s for s in new.steps}
    diff = PlanDiff(
        added=sorted(set(new_steps) - set(old_steps)),
        removed=sorted(set(old_steps) - set(new_steps)),
        budget_changed=old.total_budget_tokens != new.total_budget_tokens,
        name_changed=old.name != new.name,
    )
    for step_id in sorted(set(old_steps) & set(new_steps)):
        before, after = old_steps[step_id], new_steps[step_id]
        fields: dict[str, tuple[Any, Any]] = {}
        for name in _DIFF_FIELDS:
            old_value = getattr(before, name)
            new_value = getattr(after, name)
            if old_value != new_value:
                fields[name] = (old_value, new_value)
        if fields:
            diff.changed.append(StepChange(step_id=step_id, fields=fields))
    return diff
