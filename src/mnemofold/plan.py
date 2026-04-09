"""Plan DSL and execution loop.

Versioned JSON plan schema with steps, typed inputs/outputs,
preconditions/effects, dependency DAG validation, topological planner,
and a perceive-plan-act-observe loop with budgets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from mnemofold.approvals import ApprovalQueue, ApprovalRequest, ApprovalStatus
from mnemofold.canon import sha256_hex
from mnemofold.persist import read_envelope, write_envelope
from mnemofold.tools import ToolPolicyError, ToolRegistry, ToolValidationError

PLAN_SCHEMA = "plan"
PLAN_VERSION = 1


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
    cost_money: float = 0.0
    requires_approval: bool = False
    approver: str = ""
    status: str = "pending"  # pending, running, completed, failed, skipped, deferred, denied


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
    money_budget: float = 0.0  # 0 means unlimited
    money_spent: float = 0.0

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
                    "budget_tokens": s.budget_tokens,
                    "cost_money": round(s.cost_money, 6),
                    "requires_approval": s.requires_approval,
                    "approver": s.approver,
                    "status": s.status,
                }
                for s in self.steps
            ],
            "total_budget_tokens": self.total_budget_tokens,
            "step_budget": self.step_budget,
            "money_budget": self.money_budget,
            "money_spent": round(self.money_spent, 6),
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
            money_budget=d.get("money_budget", 0.0),
            money_spent=d.get("money_spent", 0.0),
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
                    budget_tokens=sd.get("budget_tokens", 0),
                    cost_money=sd.get("cost_money", 0.0),
                    requires_approval=sd.get("requires_approval", False),
                    approver=sd.get("approver", ""),
                    status=sd.get("status", "pending"),
                )
            )
        return plan

    def digest(self) -> str:
        """SHA-256 over the canonical JSON of :meth:`to_dict`.

        Captures the plan definition and current execution state, so two
        independently built identical plans digest equal. Used by golden
        tests and cross-run reproducibility checks.
        """
        return sha256_hex(self.to_dict())

    def save(self, path: str | Path) -> None:
        """Write the plan to ``path`` as a versioned envelope."""
        write_envelope(path, PLAN_SCHEMA, self.to_dict(), version=PLAN_VERSION)

    @classmethod
    def load(cls, path: str | Path) -> Plan:
        """Load a plan written by :meth:`save`."""
        return cls.from_dict(read_envelope(path, PLAN_SCHEMA, version=PLAN_VERSION))


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


@dataclass(slots=True)
class StepOutcome:
    """Result of executing one plan step."""

    step_id: str
    status: str  # completed | failed | skipped | deferred
    output: Any = None
    error: str = ""
    tokens_spent: int = 0
    money_spent: float = 0.0


@dataclass
class PlanLoop:
    """Perceive-plan-act-observe loop with step and token budgets.

    Execution rules (all deterministic):

    * the next runnable step is the first ``pending`` step in declaration
      order whose dependencies all completed;
    * a step whose ``budget_tokens`` or ``cost_money`` would exceed the
      remaining plan budgets is marked ``skipped`` and costs nothing;
    * tool failures and validation/policy errors mark the step (and the
      plan) failed and stop the loop;
    * successful outputs are bound to the step's declared ``outputs``
      names so later steps can reference them via ``$step.output``.
    """

    plan: Plan
    current_step_index: int = 0
    iteration: int = 0
    max_iterations: int = 100
    approvals: ApprovalQueue | None = None
    now: datetime | None = None
    world: dict[str, Any] = field(default_factory=dict)
    _outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def can_continue(self) -> bool:
        if self.plan.token_used >= self.plan.total_budget_tokens:
            return False
        if self.plan.money_budget > 0 and self.plan.money_spent >= self.plan.money_budget:
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

    def budget_snapshot(self) -> dict[str, Any]:
        """Current budget state, with floats quantized for stable serialization.

        Returns remaining and spent values for every budget dimension
        (steps, tokens, money) so reports and approval workflows can
        render progress without reading plan internals directly. Money
        is expressed as ``remaining_money`` = budget - spent (infinite
        when no money budget is set).
        """
        total_steps = len(self.plan.steps)
        completed = self.steps_completed()
        tokens_total = self.plan.total_budget_tokens
        tokens_used = self.plan.token_used
        money_total = self.plan.money_budget
        money_spent = self.plan.money_spent
        remaining_money: float | None = None
        if money_total > 0:
            remaining_money = round(max(0.0, money_total - money_spent), 6)
        return {
            "steps_total": total_steps,
            "steps_completed": completed,
            "steps_remaining": total_steps - completed,
            "tokens_total": tokens_total,
            "tokens_used": tokens_used,
            "tokens_remaining": max(0, tokens_total - tokens_used),
            "money_total": round(money_total, 6),
            "money_spent": round(money_spent, 6),
            "remaining_money": remaining_money,
            "iterations": self.iteration,
            "status": str(self.plan.status),
        }

    def next_runnable(self) -> PlanStep | None:
        completed = {s.step_id for s in self.plan.steps if s.status == "completed"}
        for step in self.plan.steps:
            if step.status != "pending":
                continue
            if not all(dep in completed for dep in step.depends_on):
                continue
            if not self.preconditions_met(step):
                continue
            return step
        return None

    def preconditions_met(self, step: PlanStep) -> bool:
        """True when every precondition holds against the observed world.

        A precondition is ``key`` (truthy presence) or ``key=value``
        (equality after JSON-parsing the value). Empty conditions are
        ignored, so a step with no preconditions is always eligible.
        """
        for condition in step.preconditions:
            key, sep, raw = condition.partition("=")
            key = key.strip()
            if not key:
                continue
            if not sep:
                if not self.world.get(key):
                    return False
            elif self.world.get(key) != _parse_value(raw.strip()):
                return False
        return True

    def observe(self, step: PlanStep) -> None:
        """Apply a completed step's effects to the world state.

        Effects are ``key=value`` strings (a bare ``key`` sets True).
        Values are JSON-parsed when possible so numbers and booleans
        round-trip; otherwise they are kept as strings. This is the
        observe half of the perceive-plan-act-observe loop: later steps
        read the world through their preconditions.
        """
        for effect in step.effects:
            key, sep, raw = effect.partition("=")
            key = key.strip()
            if not key:
                continue
            if not sep:
                self.world[key] = True
            else:
                self.world[key] = _parse_value(raw.strip())

    def output_of(self, step_id: str, output_name: str) -> Any:
        """A previously bound step output (None when absent)."""
        return self._outputs.get(step_id, {}).get(output_name)

    def _resolve_inputs(self, step: PlanStep) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for name, value in step.inputs.items():
            ref = _reference_parts(value)
            if ref is None:
                resolved[name] = value
            else:
                ref_step, ref_output = ref
                resolved[name] = self._outputs.get(ref_step, {}).get(ref_output)
        return resolved

    def _bind_outputs(self, step: PlanStep, output: Any) -> None:
        bound: dict[str, Any] = {}
        if (
            isinstance(output, dict)
            and step.outputs
            and all(name in output for name in step.outputs)
        ):
            for name in step.outputs:
                bound[name] = output[name]
        elif step.outputs:
            bound[step.outputs[0]] = output
        self._outputs[step.step_id] = bound

    def _check_approval(self, step: PlanStep) -> str:
        """Resolve a step's approval gate: 'approved', 'denied', or 'deferred'.

        Steps that do not require approval pass straight through. When a
        step requires approval but no :class:`ApprovalQueue` is wired, the
        step is deferred rather than silently run — an unguarded side
        effect is never executed. When a queue is present, a request is
        submitted (once) and driven by the scripted personas; a still-open
        request defers the step.
        """
        if not step.requires_approval:
            return "approved"
        if self.approvals is None:
            return "deferred"
        request_id = f"{self.plan.plan_id}:{step.step_id}"
        existing = next((r for r in self.approvals.requests if r.request_id == request_id), None)
        if existing is None:
            self.approvals.submit(
                ApprovalRequest(
                    request_id=request_id,
                    item_id=step.step_id,
                    item_kind="plan_step",
                    summary=f"Execute plan step '{step.name}'",
                    requester=self.plan.plan_id,
                    approver=step.approver or "plan-approver",
                    created_at=self.now,
                )
            )
        if self.now is not None:
            self.approvals.auto_resolve(self.now)
            self.approvals.tick_expirations(self.now)
        request = next((r for r in self.approvals.requests if r.request_id == request_id), None)
        if request is None:
            return "deferred"
        if request.status == ApprovalStatus.APPROVED:
            return "approved"
        if request.status in (ApprovalStatus.DENIED, ApprovalStatus.EXPIRED):
            return "denied"
        return "deferred"

    def run_step(self, registry: ToolRegistry) -> StepOutcome | None:
        step = self.next_runnable()
        if step is None:
            return None
        self.iteration += 1
        gate = self._check_approval(step)
        if gate == "denied":
            step.status = "denied"
            self.plan.status = PlanStatus.FAILED
            return StepOutcome(step_id=step.step_id, status="denied", error="approval denied")
        if gate == "deferred":
            step.status = "deferred"
            return StepOutcome(step_id=step.step_id, status="deferred", error="awaiting approval")
        cost = max(0, step.budget_tokens)
        if self.plan.token_used + cost > self.plan.total_budget_tokens:
            step.status = "skipped"
            return StepOutcome(
                step_id=step.step_id, status="skipped", error="token budget exhausted"
            )
        money_cost = max(0.0, step.cost_money)
        if (
            self.plan.money_budget > 0
            and self.plan.money_spent + money_cost > self.plan.money_budget
        ):
            step.status = "skipped"
            return StepOutcome(
                step_id=step.step_id, status="skipped", error="money budget exhausted"
            )
        if not step.tool:
            step.status = "completed"
            self.plan.token_used += cost
            self.plan.money_spent = round(self.plan.money_spent + money_cost, 6)
            return StepOutcome(
                step_id=step.step_id,
                status="completed",
                tokens_spent=cost,
                money_spent=money_cost,
            )
        try:
            result = registry.invoke(step.tool, self._resolve_inputs(step))
        except (ToolValidationError, ToolPolicyError) as exc:
            step.status = "failed"
            self.plan.status = PlanStatus.FAILED
            self.plan.token_used += cost
            self.plan.money_spent = round(self.plan.money_spent + money_cost, 6)
            return StepOutcome(
                step_id=step.step_id,
                status="failed",
                error=str(exc),
                tokens_spent=cost,
                money_spent=money_cost,
            )
        self.plan.token_used += cost
        self.plan.money_spent = round(self.plan.money_spent + money_cost, 6)
        if result.success:
            step.status = "completed"
            self._bind_outputs(step, result.output)
            return StepOutcome(
                step_id=step.step_id,
                status="completed",
                output=result.output,
                tokens_spent=cost,
                money_spent=money_cost,
            )
        step.status = "failed"
        self.plan.status = PlanStatus.FAILED
        return StepOutcome(
            step_id=step.step_id,
            status="failed",
            error=result.error,
            tokens_spent=cost,
            money_spent=money_cost,
        )

    def run_to_completion(self, registry: ToolRegistry) -> list[StepOutcome]:
        if self.plan.status in {PlanStatus.DRAFT, PlanStatus.VALID}:
            self.plan.status = PlanStatus.RUNNING
        for step in self.plan.steps:
            if step.status == "deferred":
                step.status = "pending"  # a fresh pass re-asks the approver
        outcomes: list[StepOutcome] = []
        steps_by_id = {s.step_id: s for s in self.plan.steps}
        while self.can_continue():
            outcome = self.run_step(registry)
            if outcome is None:
                break
            if outcome.status == "completed":
                self.observe(steps_by_id[outcome.step_id])
            outcomes.append(outcome)
        if self.plan.status not in {PlanStatus.FAILED, PlanStatus.CANCELLED}:
            unfinished = [s for s in self.plan.steps if s.status != "completed"]
            if not unfinished:
                self.plan.status = PlanStatus.COMPLETED
            elif any(s.status == "deferred" for s in unfinished) and all(
                s.status in ("pending", "deferred") for s in unfinished
            ):
                # blocked on approvals only: resumable, not failed
                self.plan.status = PlanStatus.RUNNING
            else:
                self.plan.status = PlanStatus.FAILED
        return outcomes


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


def _parse_value(raw: str) -> Any:
    """Parse an effect/precondition value: JSON when possible, else string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw
