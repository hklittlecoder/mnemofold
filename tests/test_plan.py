from datetime import UTC, datetime, timedelta

from mnemofold.approvals import ApprovalQueue, ApprovalStatus, Approver, ApproverPersona
from mnemofold.plan import (
    Plan,
    PlanDiff,
    PlanLoop,
    PlanStatus,
    PlanStep,
    PlanValidationResult,
    diff_plans,
    topological_order,
    validate_plan,
)
from mnemofold.tools import ToolRegistry, ToolSpec, build_default_registry


def test_plan_status_enum():
    assert PlanStatus.DRAFT == "draft"
    assert PlanStatus.COMPLETED == "completed"


def test_plan_step_defaults():
    step = PlanStep(step_id="s1", name="first")
    assert step.step_id == "s1"
    assert step.name == "first"
    assert step.tool == ""
    assert step.inputs == {}
    assert step.outputs == []
    assert step.preconditions == []
    assert step.effects == []
    assert step.depends_on == []
    assert step.status == "pending"


def test_plan_creation_and_status_coercion():
    plan = Plan(plan_id="p1", name="test plan")
    assert plan.status == PlanStatus.DRAFT
    plan2 = Plan(plan_id="p2", name="test", status="running")
    assert plan2.status == PlanStatus.RUNNING


def test_plan_roundtrip_dict():
    plan = Plan(
        plan_id="p1",
        name="roundtrip",
        version=2,
        total_budget_tokens=5000,
        step_budget=50,
        metadata={"env": "test"},
        steps=[
            PlanStep(
                step_id="a",
                name="alpha",
                tool="noop",
                inputs={"x": 1},
                outputs=["y"],
                preconditions=["ready"],
                effects=["done"],
                depends_on=[],
                budget_tokens=100,
                status="completed",
            ),
            PlanStep(step_id="b", name="beta", depends_on=["a"]),
        ],
    )
    d = plan.to_dict()
    plan2 = Plan.from_dict(d)
    assert plan2.plan_id == plan.plan_id
    assert plan2.version == plan.version
    assert plan2.total_budget_tokens == plan.total_budget_tokens
    assert plan2.step_budget == plan.step_budget
    assert plan2.metadata == plan.metadata
    assert len(plan2.steps) == len(plan.steps)
    assert plan2.steps[0].step_id == "a"
    assert plan2.steps[0].tool == "noop"
    assert plan2.steps[0].inputs == {"x": 1}
    assert plan2.steps[0].outputs == ["y"]
    assert plan2.steps[1].depends_on == ["a"]


def test_validate_valid_dag():
    plan = Plan(
        plan_id="p",
        name="ok",
        steps=[
            PlanStep(step_id="a", name="A"),
            PlanStep(step_id="b", name="B", depends_on=["a"]),
            PlanStep(step_id="c", name="C", depends_on=["a", "b"]),
        ],
    )
    result = validate_plan(plan)
    assert result.valid
    assert result.errors == []


def test_validate_dangling_dep():
    plan = Plan(
        plan_id="p",
        name="bad",
        steps=[PlanStep(step_id="a", name="A", depends_on=["z"])],
    )
    result = validate_plan(plan)
    assert not result.valid
    assert any("unknown step" in e for e in result.errors)


def test_validate_self_dep():
    plan = Plan(
        plan_id="p",
        name="bad",
        steps=[PlanStep(step_id="a", name="A", depends_on=["a"])],
    )
    result = validate_plan(plan)
    assert not result.valid
    assert any("itself" in e for e in result.errors)


def test_validate_cycle():
    plan = Plan(
        plan_id="p",
        name="cycle",
        steps=[
            PlanStep(step_id="a", name="A", depends_on=["b"]),
            PlanStep(step_id="b", name="B", depends_on=["a"]),
        ],
    )
    result = validate_plan(plan)
    assert not result.valid
    assert any("cycle" in e for e in result.errors)


def test_validate_budget_warning():
    plan = Plan(
        plan_id="p",
        name="warn",
        total_budget_tokens=100,
        steps=[
            PlanStep(step_id="a", name="A", budget_tokens=80),
            PlanStep(step_id="b", name="B", budget_tokens=50),
        ],
    )
    result = validate_plan(plan)
    assert result.valid
    assert any("exceeds total budget" in w for w in result.warnings)


def test_topological_order_basic():
    plan = Plan(
        plan_id="p",
        name="t",
        steps=[
            PlanStep(step_id="c", name="C", depends_on=["a", "b"]),
            PlanStep(step_id="a", name="A"),
            PlanStep(step_id="b", name="B", depends_on=["a"]),
        ],
    )
    order = topological_order(plan)
    assert order.index("a") < order.index("b")
    assert order.index("b") < order.index("c")


def test_topological_order_deterministic():
    plan = Plan(
        plan_id="p",
        name="t",
        steps=[
            PlanStep(step_id="z", name="Z"),
            PlanStep(step_id="a", name="A"),
            PlanStep(step_id="m", name="M"),
        ],
    )
    order = topological_order(plan)
    assert order == ["a", "m", "z"]


def test_plan_validation_result():
    r = PlanValidationResult(valid=True)
    assert r.valid
    assert r.errors == []
    assert r.warnings == []


def test_plan_loop_basics():
    plan = Plan(
        plan_id="p",
        name="loop",
        steps=[
            PlanStep(step_id="a", name="A", status="completed"),
            PlanStep(step_id="b", name="B", status="failed"),
            PlanStep(step_id="c", name="C", status="pending"),
        ],
    )
    loop = PlanLoop(plan=plan)
    assert loop.steps_completed() == 1
    assert loop.steps_failed() == 1
    assert loop.can_continue() is True


def test_plan_loop_stops_on_completed():
    plan = Plan(plan_id="p", name="done", status=PlanStatus.COMPLETED)
    loop = PlanLoop(plan=plan)
    assert loop.can_continue() is False


def test_plan_loop_token_budget():
    plan = Plan(plan_id="p", name="budget", total_budget_tokens=100)
    plan.token_used = 100
    loop = PlanLoop(plan=plan)
    assert loop.can_continue() is False


def test_budget_snapshot_initial_state():
    plan = Plan(
        plan_id="p",
        name="budget-snap",
        total_budget_tokens=1000,
        money_budget=10.0,
        steps=[
            PlanStep(step_id="a", name="A"),
            PlanStep(step_id="b", name="B"),
            PlanStep(step_id="c", name="C"),
        ],
    )
    loop = PlanLoop(plan=plan)
    snap = loop.budget_snapshot()
    assert snap["steps_total"] == 3
    assert snap["steps_completed"] == 0
    assert snap["tokens_total"] == 1000
    assert snap["tokens_used"] == 0
    assert snap["tokens_remaining"] == 1000
    assert abs(snap["money_total"] - 10.0) < 1e-9
    assert snap["money_spent"] == 0.0
    assert snap["remaining_money"] is not None
    assert abs(snap["remaining_money"] - 10.0) < 1e-9
    assert snap["status"] == str(PlanStatus.DRAFT)


def test_budget_snapshot_no_money_budget_returns_none_remaining():
    plan = Plan(plan_id="p", name="free", total_budget_tokens=100)
    loop = PlanLoop(plan=plan)
    snap = loop.budget_snapshot()
    assert snap["remaining_money"] is None


def test_plan_loop_max_iterations():
    plan = Plan(plan_id="p", name="iters")
    loop = PlanLoop(plan=plan, iteration=100, max_iterations=100)
    assert loop.can_continue() is False


class TestPlanInputReferences:
    def _plan(self, inputs: dict) -> Plan:
        return Plan(
            plan_id="p1",
            name="refs",
            steps=[
                PlanStep(
                    step_id="a",
                    name="produce",
                    tool="echo",
                    inputs={"message": "seed"},
                    outputs=["text"],
                ),
                PlanStep(step_id="b", name="consume", tool="echo", inputs=inputs, depends_on=["a"]),
            ],
        )

    def test_valid_reference_passes(self):
        result = validate_plan(self._plan({"message": "$a.text"}))
        assert result.valid
        assert result.errors == []

    def test_unknown_step_reference_rejected(self):
        result = validate_plan(self._plan({"message": "$ghost.text"}))
        assert not result.valid
        assert any("unknown step 'ghost'" in e for e in result.errors)

    def test_undeclared_output_reference_rejected(self):
        result = validate_plan(self._plan({"message": "$a.missing"}))
        assert not result.valid
        assert any("undeclared output 'missing'" in e for e in result.errors)

    def test_self_reference_rejected(self):
        plan = Plan(
            plan_id="p",
            name="self",
            steps=[
                PlanStep(
                    step_id="a",
                    name="loop",
                    tool="echo",
                    inputs={"message": "$a.text"},
                    outputs=["text"],
                ),
            ],
        )
        result = validate_plan(plan)
        assert not result.valid
        assert any("references itself" in e for e in result.errors)

    def test_literal_values_are_untouched(self):
        result = validate_plan(self._plan({"message": "plain text", "count": 3}))
        assert result.valid

    def test_dollar_without_dot_is_a_step_only_reference_error(self):
        # "$a" names a step but no output; partition yields ("a", "")
        result = validate_plan(self._plan({"message": "$a"}))
        assert not result.valid
        assert any("undeclared output ''" in e for e in result.errors)


class TestPlanDiff:
    def _plan(self, steps: list[PlanStep], name: str = "p", budget: int = 1000) -> Plan:
        return Plan(plan_id="p1", name=name, total_budget_tokens=budget, steps=steps)

    def test_identical_plans_diff_empty(self):
        steps = [PlanStep(step_id="a", name="A", tool="echo")]
        diff: PlanDiff = diff_plans(self._plan(list(steps)), self._plan(list(steps)))
        assert diff.is_empty()

    def test_added_and_removed_steps(self):
        old = self._plan([PlanStep(step_id="a", name="A"), PlanStep(step_id="b", name="B")])
        new = self._plan([PlanStep(step_id="b", name="B"), PlanStep(step_id="c", name="C")])
        diff = diff_plans(old, new)
        assert diff.added == ["c"]
        assert diff.removed == ["a"]
        assert diff.changed == []

    def test_changed_fields_captured_with_old_new(self):
        old = self._plan([PlanStep(step_id="a", name="A", tool="echo", budget_tokens=10)])
        new = self._plan([PlanStep(step_id="a", name="A", tool="noop", budget_tokens=20)])
        diff = diff_plans(old, new)
        assert len(diff.changed) == 1
        change = diff.changed[0]
        assert change.step_id == "a"
        assert change.fields["tool"] == ("echo", "noop")
        assert change.fields["budget_tokens"] == (10, 20)

    def test_plan_level_flags(self):
        old = self._plan([PlanStep(step_id="a", name="A")], name="old", budget=100)
        new = self._plan([PlanStep(step_id="a", name="A")], name="new", budget=200)
        diff = diff_plans(old, new)
        assert diff.name_changed
        assert diff.budget_changed
        assert diff.added == [] and diff.removed == [] and diff.changed == []

    def test_changed_steps_sorted_by_id(self):
        old = self._plan([PlanStep(step_id="z", name="Z"), PlanStep(step_id="m", name="M")])
        new = self._plan([PlanStep(step_id="z", name="Z2"), PlanStep(step_id="m", name="M2")])
        diff = diff_plans(old, new)
        assert [c.step_id for c in diff.changed] == ["m", "z"]


def _echo_registry() -> ToolRegistry:
    registry = build_default_registry()  # echo(message) + noop()
    registry.register(
        ToolSpec(name="boom", description="always fails", max_retries=0),
        lambda: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    return registry


class TestPlanLoopExecution:
    def test_runs_steps_in_dependency_order(self):
        plan = Plan(
            plan_id="p",
            name="chain",
            steps=[
                PlanStep(
                    step_id="a",
                    name="A",
                    tool="echo",
                    inputs={"message": "hello"},
                    outputs=["text"],
                    budget_tokens=10,
                ),
                PlanStep(
                    step_id="b",
                    name="B",
                    tool="echo",
                    inputs={"message": "$a.text"},
                    outputs=["text"],
                    depends_on=["a"],
                    budget_tokens=10,
                ),
            ],
        )
        loop = PlanLoop(plan=plan)
        outcomes = loop.run_to_completion(_echo_registry())
        assert [o.step_id for o in outcomes] == ["a", "b"]
        assert all(o.status == "completed" for o in outcomes)
        # b echoed a's output through the $a.text reference
        assert outcomes[1].output == "hello"
        assert plan.status == PlanStatus.COMPLETED

    def test_token_budget_accumulates(self):
        plan = Plan(
            plan_id="p",
            name="b",
            total_budget_tokens=1000,
            steps=[
                PlanStep(step_id="a", name="A", tool="noop", budget_tokens=100),
                PlanStep(step_id="b", name="B", tool="noop", budget_tokens=250),
            ],
        )
        PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert plan.token_used == 350

    def test_step_exceeding_budget_is_skipped(self):
        plan = Plan(
            plan_id="p",
            name="tight",
            total_budget_tokens=150,
            steps=[
                PlanStep(step_id="a", name="A", tool="noop", budget_tokens=100),
                PlanStep(step_id="big", name="Big", tool="noop", budget_tokens=100),
            ],
        )
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        statuses = {o.step_id: o.status for o in outcomes}
        assert statuses["a"] == "completed"
        assert statuses["big"] == "skipped"
        assert plan.token_used == 100  # skipped step spends nothing

    def test_failing_tool_fails_plan(self):
        plan = Plan(
            plan_id="p",
            name="fail",
            steps=[
                PlanStep(step_id="a", name="A", tool="boom"),
                PlanStep(step_id="b", name="B", tool="noop", depends_on=["a"]),
            ],
        )
        loop = PlanLoop(plan=plan)
        outcomes = loop.run_to_completion(_echo_registry())
        assert outcomes[0].status == "failed"
        assert "kaboom" in outcomes[0].error
        assert plan.status == PlanStatus.FAILED
        # b never ran because its dependency failed
        assert loop.steps_completed() == 0

    def test_validation_error_fails_step(self):
        plan = Plan(
            plan_id="p",
            name="bad",
            steps=[PlanStep(step_id="a", name="A", tool="echo", inputs={})],  # missing message
        )
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert outcomes[0].status == "failed"
        assert "message" in outcomes[0].error

    def test_max_iterations_caps_loop(self):
        plan = Plan(
            plan_id="p",
            name="many",
            steps=[PlanStep(step_id=f"s{i}", name=f"S{i}", tool="noop") for i in range(10)],
        )
        loop = PlanLoop(plan=plan, max_iterations=3)
        outcomes = loop.run_to_completion(_echo_registry())
        assert len(outcomes) == 3
        assert loop.iteration == 3

    def test_completed_plan_cannot_continue(self):
        plan = Plan(plan_id="p", name="x", status=PlanStatus.COMPLETED, steps=[])
        loop = PlanLoop(plan=plan)
        assert loop.can_continue() is False

    def test_empty_plan_completes(self):
        plan = Plan(plan_id="p", name="empty", steps=[])
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert outcomes == []
        assert plan.status == PlanStatus.COMPLETED


class TestMoneyBudget:
    def test_unlimited_by_default(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[PlanStep(step_id="a", name="A", tool="noop", cost_money=1000.0)],
        )
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert outcomes[0].status == "completed"
        assert plan.money_spent == 1000.0

    def test_spending_accumulates(self):
        plan = Plan(
            plan_id="p",
            name="n",
            money_budget=10.0,
            steps=[
                PlanStep(step_id="a", name="A", tool="noop", cost_money=1.5),
                PlanStep(step_id="b", name="B", tool="noop", cost_money=2.25),
            ],
        )
        PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert plan.money_spent == 3.75
        assert plan.status == PlanStatus.COMPLETED

    def test_insufficient_money_skips_step(self):
        plan = Plan(
            plan_id="p",
            name="n",
            money_budget=5.0,
            steps=[
                PlanStep(step_id="a", name="A", tool="noop", cost_money=4.0),
                PlanStep(step_id="b", name="B", tool="noop", cost_money=4.0),
            ],
        )
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        statuses = {o.step_id: o.status for o in outcomes}
        assert statuses["a"] == "completed"
        assert statuses["b"] == "skipped"
        assert plan.money_spent == 4.0
        assert plan.status == PlanStatus.FAILED  # skipped work leaves the plan unfinished

    def test_failed_tool_still_charges_money(self):
        plan = Plan(
            plan_id="p",
            name="n",
            money_budget=10.0,
            steps=[PlanStep(step_id="a", name="A", tool="boom", cost_money=3.0)],
        )
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert outcomes[0].status == "failed"
        assert plan.money_spent == 3.0

    def test_can_continue_false_when_money_exhausted(self):
        plan = Plan(plan_id="p", name="n", money_budget=5.0, money_spent=5.0, steps=[])
        assert PlanLoop(plan=plan).can_continue() is False

    def test_outcome_reports_money_spent(self):
        plan = Plan(
            plan_id="p",
            name="n",
            money_budget=10.0,
            steps=[PlanStep(step_id="a", name="A", tool="noop", cost_money=2.5)],
        )
        outcomes = PlanLoop(plan=plan).run_to_completion(_echo_registry())
        assert outcomes[0].money_spent == 2.5

    def test_serialization_roundtrip_includes_budgets(self):
        plan = Plan(
            plan_id="p",
            name="n",
            money_budget=9.5,
            steps=[PlanStep(step_id="a", name="A", budget_tokens=10, cost_money=1.25)],
        )
        restored = Plan.from_dict(plan.to_dict())
        assert restored.money_budget == 9.5
        assert restored.steps[0].cost_money == 1.25
        # budget_tokens was previously dropped by to_dict; it now round-trips
        assert restored.steps[0].budget_tokens == 10


APPROVAL_NOW = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


def _approval_queue(persona: ApproverPersona, latency: timedelta = timedelta()) -> ApprovalQueue:
    queue = ApprovalQueue()
    queue.add_approver(Approver(name="plan-approver", persona=persona, decision_latency=latency))
    return queue


class TestApprovalGatedSteps:
    def _plan(self) -> Plan:
        return Plan(
            plan_id="p",
            name="gated",
            steps=[
                PlanStep(step_id="a", name="A", tool="noop", requires_approval=True),
                PlanStep(step_id="b", name="B", tool="noop", depends_on=["a"]),
            ],
        )

    def test_auto_approve_executes_step(self):
        plan = self._plan()
        loop = PlanLoop(
            plan=plan,
            approvals=_approval_queue(ApproverPersona.AUTO_APPROVE),
            now=APPROVAL_NOW,
        )
        outcomes = loop.run_to_completion(_echo_registry())
        assert [o.status for o in outcomes] == ["completed", "completed"]
        assert plan.status == PlanStatus.COMPLETED

    def test_auto_deny_fails_step_and_plan(self):
        plan = self._plan()
        loop = PlanLoop(
            plan=plan,
            approvals=_approval_queue(ApproverPersona.AUTO_DENY),
            now=APPROVAL_NOW,
        )
        outcomes = loop.run_to_completion(_echo_registry())
        assert outcomes[0].status == "denied"
        assert plan.status == PlanStatus.FAILED
        assert plan.steps[1].status == "pending"  # dependent never ran

    def test_ask_persona_defers_then_resumes(self):
        plan = self._plan()
        queue = _approval_queue(ApproverPersona.ASK)
        loop = PlanLoop(plan=plan, approvals=queue, now=APPROVAL_NOW)
        outcomes = loop.run_to_completion(_echo_registry())
        assert outcomes[0].status == "deferred"
        assert plan.status == PlanStatus.RUNNING  # resumable, not failed
        # a decision lands, then the same loop resumes where it left off
        queue.decide("p:a", True, APPROVAL_NOW)
        resumed = loop.run_to_completion(_echo_registry())
        assert [o.status for o in resumed] == ["completed", "completed"]
        assert plan.status == PlanStatus.COMPLETED

    def test_missing_queue_defers_instead_of_running(self):
        plan = self._plan()
        outcomes = PlanLoop(plan=plan, now=APPROVAL_NOW).run_to_completion(_echo_registry())
        assert outcomes[0].status == "deferred"
        assert plan.status == PlanStatus.RUNNING

    def test_denial_recorded_in_queue(self):
        plan = self._plan()
        queue = _approval_queue(ApproverPersona.AUTO_DENY)
        PlanLoop(plan=plan, approvals=queue, now=APPROVAL_NOW).run_to_completion(_echo_registry())
        request = queue.requests[0]
        assert request.request_id == "p:a"
        assert request.item_kind == "plan_step"
        assert request.status == ApprovalStatus.DENIED
        assert request.decision_note == "auto-denied"

    def test_request_submitted_only_once_across_resumes(self):
        plan = Plan(
            plan_id="p",
            name="gated",
            steps=[PlanStep(step_id="a", name="A", tool="noop", requires_approval=True)],
        )
        queue = _approval_queue(ApproverPersona.ASK)
        loop = PlanLoop(plan=plan, approvals=queue, now=APPROVAL_NOW)
        loop.run_to_completion(_echo_registry())
        # second pass must not duplicate the request even though the step
        # was reset for the resume
        plan.steps[0].status = "pending"
        loop.run_to_completion(_echo_registry())
        assert len(queue.requests) == 1

    def test_custom_approver_name(self):
        plan = Plan(
            plan_id="p",
            name="gated",
            steps=[
                PlanStep(
                    step_id="a",
                    name="A",
                    tool="noop",
                    requires_approval=True,
                    approver="alice",
                )
            ],
        )
        queue = ApprovalQueue()
        queue.add_approver(
            Approver(
                name="alice",
                persona=ApproverPersona.AUTO_APPROVE,
                decision_latency=timedelta(),
            )
        )
        loop = PlanLoop(plan=plan, approvals=queue, now=APPROVAL_NOW)
        outcomes = loop.run_to_completion(_echo_registry())
        assert outcomes[0].status == "completed"
        assert queue.requests[0].approver == "alice"

    def test_serialization_roundtrip_includes_gate(self):
        plan = self._plan()
        restored = Plan.from_dict(plan.to_dict())
        assert restored.steps[0].requires_approval is True
        assert restored.steps[0].approver == ""

    def test_denied_step_charges_no_budget(self):
        plan = Plan(
            plan_id="p",
            name="gated",
            steps=[
                PlanStep(
                    step_id="a",
                    name="A",
                    tool="noop",
                    requires_approval=True,
                    budget_tokens=50,
                    cost_money=5.0,
                )
            ],
        )
        loop = PlanLoop(
            plan=plan,
            approvals=_approval_queue(ApproverPersona.AUTO_DENY),
            now=APPROVAL_NOW,
        )
        loop.run_to_completion(_echo_registry())
        assert plan.token_used == 0
        assert plan.money_spent == 0.0


class TestObservePhase:
    def test_effects_populate_world(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[
                PlanStep(step_id="a", name="A", tool="noop", effects=["ready=true", "count=3"]),
            ],
        )
        loop = PlanLoop(plan=plan)
        loop.run_to_completion(_echo_registry())
        assert loop.world == {"ready": True, "count": 3}

    def test_bare_effect_sets_true(self):
        plan = Plan(
            plan_id="p", name="n", steps=[PlanStep(step_id="a", name="A", effects=["done"])]
        )
        loop = PlanLoop(plan=plan)
        loop.run_to_completion(_echo_registry())
        assert loop.world["done"] is True

    def test_unparseable_effect_stays_string(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[PlanStep(step_id="a", name="A", effects=["name=alpha plan"])],
        )
        loop = PlanLoop(plan=plan)
        loop.run_to_completion(_echo_registry())
        assert loop.world["name"] == "alpha plan"

    def test_precondition_orders_steps_without_dependencies(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[
                PlanStep(step_id="gate", name="Gate", tool="noop", preconditions=["ready"]),
                PlanStep(step_id="setup", name="Setup", tool="noop", effects=["ready=true"]),
            ],
        )
        loop = PlanLoop(plan=plan)
        outcomes = loop.run_to_completion(_echo_registry())
        # declared gate-first, but setup must run first to satisfy the world
        assert [o.step_id for o in outcomes] == ["setup", "gate"]
        assert plan.status == PlanStatus.COMPLETED

    def test_unsatisfiable_precondition_fails_plan(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[PlanStep(step_id="a", name="A", tool="noop", preconditions=["never_set"])],
        )
        loop = PlanLoop(plan=plan)
        outcomes = loop.run_to_completion(_echo_registry())
        assert outcomes == []
        assert plan.status == PlanStatus.FAILED
        assert plan.steps[0].status == "pending"

    def test_value_preconditions_match_exactly(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[
                PlanStep(step_id="s1", name="S1", tool="noop", effects=["env=prod"]),
                PlanStep(step_id="s2", name="S2", tool="noop", preconditions=["env=prod"]),
                PlanStep(step_id="s3", name="S3", tool="noop", preconditions=["env=staging"]),
            ],
        )
        loop = PlanLoop(plan=plan)
        outcomes = loop.run_to_completion(_echo_registry())
        assert {o.step_id for o in outcomes} == {"s1", "s2"}
        assert plan.steps[2].status == "pending"
        assert plan.status == PlanStatus.FAILED

    def test_toolless_steps_also_observe(self):
        plan = Plan(plan_id="p", name="n", steps=[PlanStep(step_id="a", name="A", effects=["x=1"])])
        loop = PlanLoop(plan=plan)
        loop.run_to_completion(_echo_registry())
        assert loop.world == {"x": 1}

    def test_preseeded_world_satisfies_preconditions(self):
        plan = Plan(
            plan_id="p",
            name="n",
            steps=[PlanStep(step_id="a", name="A", tool="noop", preconditions=["env=prod"])],
        )
        loop = PlanLoop(plan=plan, world={"env": "prod"})
        outcomes = loop.run_to_completion(_echo_registry())
        assert [o.status for o in outcomes] == ["completed"]


class TestPlanLoopMatrix:
    """Money, tokens, approvals, preconditions, and outputs in one plan."""

    def _matrix_plan(self) -> Plan:
        return Plan(
            plan_id="mx",
            name="matrix",
            money_budget=10.0,
            total_budget_tokens=100,
            steps=[
                PlanStep(
                    step_id="setup",
                    name="Setup",
                    tool="noop",
                    budget_tokens=10,
                    cost_money=2.0,
                    effects=["env=ready"],
                ),
                PlanStep(
                    step_id="deploy",
                    name="Deploy",
                    tool="echo",
                    inputs={"message": "ship"},
                    outputs=["out"],
                    preconditions=["env=ready"],
                    requires_approval=True,
                    depends_on=["setup"],
                    budget_tokens=20,
                    cost_money=5.0,
                ),
                PlanStep(
                    step_id="expensive",
                    name="Expensive",
                    tool="noop",
                    depends_on=["deploy"],
                    budget_tokens=10,
                    cost_money=8.0,
                ),
            ],
        )

    def _run(self):
        queue = _approval_queue(ApproverPersona.AUTO_APPROVE)
        plan = self._matrix_plan()
        loop = PlanLoop(plan=plan, approvals=queue, now=APPROVAL_NOW)
        outcomes = loop.run_to_completion(_echo_registry())
        return plan, loop, outcomes, queue

    def test_mixed_plan_end_to_end(self):
        plan, loop, outcomes, queue = self._run()
        statuses = {o.step_id: o.status for o in outcomes}
        assert statuses == {
            "setup": "completed",
            "deploy": "completed",
            "expensive": "skipped",  # 8.0 does not fit the 3.0 remaining
        }
        assert plan.money_spent == 7.0
        assert plan.token_used == 30
        assert loop.world["env"] == "ready"
        assert loop.output_of("deploy", "out") == "ship"
        assert plan.status == PlanStatus.FAILED  # a skipped step leaves work undone
        assert queue.requests[0].status == ApprovalStatus.APPROVED

    def test_matrix_run_is_deterministic(self):
        def run_once():
            plan, loop, outcomes, _queue = self._run()
            return (
                [(o.step_id, o.status, o.tokens_spent, o.money_spent) for o in outcomes],
                plan.money_spent,
                plan.token_used,
                dict(loop.world),
            )

        assert run_once() == run_once()

    def test_denied_approval_short_circuits_downstream(self):
        queue = _approval_queue(ApproverPersona.AUTO_DENY)
        plan = self._matrix_plan()
        loop = PlanLoop(plan=plan, approvals=queue, now=APPROVAL_NOW)
        outcomes = loop.run_to_completion(_echo_registry())
        statuses = {o.step_id: o.status for o in outcomes}
        assert statuses["setup"] == "completed"
        assert statuses["deploy"] == "denied"
        assert "expensive" not in statuses  # never became runnable
        assert plan.money_spent == 2.0
        assert plan.status == PlanStatus.FAILED


class TestPlanDigest:
    def _plan(self, name: str = "p") -> Plan:
        return Plan(
            plan_id="p1",
            name=name,
            steps=[
                PlanStep(
                    step_id="a",
                    name="A",
                    tool="echo",
                    inputs={"message": "x"},
                    outputs=["o"],
                    budget_tokens=5,
                    cost_money=1.0,
                ),
                PlanStep(step_id="b", name="B", depends_on=["a"]),
            ],
        )

    def test_digest_stable_for_equal_plans(self):
        assert self._plan().digest() == self._plan().digest()

    def test_digest_changes_with_definition(self):
        assert self._plan().digest() != self._plan(name="other").digest()

    def test_digest_tracks_execution_state(self):
        plan = self._plan()
        before = plan.digest()
        PlanLoop(plan=plan).run_to_completion(_echo_registry())
        # statuses and spend are part of to_dict, so the digest moves
        assert plan.digest() != before

    def test_digest_is_sha256_hex(self):
        digest = self._plan().digest()
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_roundtrip_preserves_digest(self):
        plan = self._plan()
        restored = Plan.from_dict(plan.to_dict())
        assert restored.digest() == plan.digest()


class TestPlanSerializationGolden:
    """Literal golden for the plan wire format.

    The expected dict below is the contract: adding, removing, or
    renaming a serialized field must be a deliberate edit here, so the
    plan schema cannot drift silently.
    """

    def _golden_plan(self) -> Plan:
        return Plan(
            plan_id="golden-1",
            name="release",
            version=3,
            total_budget_tokens=5000,
            step_budget=25,
            money_budget=12.5,
            metadata={"env": "prod"},
            steps=[
                PlanStep(
                    step_id="build",
                    name="Build",
                    tool="echo",
                    inputs={"message": "building"},
                    outputs=["log"],
                    preconditions=["env=prod"],
                    effects=["built=true"],
                    depends_on=[],
                    budget_tokens=100,
                    cost_money=2.5,
                ),
                PlanStep(
                    step_id="ship",
                    name="Ship",
                    tool="noop",
                    depends_on=["build"],
                    requires_approval=True,
                    approver="release-manager",
                    cost_money=10.0,
                ),
            ],
        )

    def test_to_dict_matches_literal(self):
        expected = {
            "plan_id": "golden-1",
            "name": "release",
            "version": 3,
            "status": "draft",
            "total_budget_tokens": 5000,
            "step_budget": 25,
            "money_budget": 12.5,
            "money_spent": 0.0,
            "metadata": {"env": "prod"},
            "steps": [
                {
                    "step_id": "build",
                    "name": "Build",
                    "tool": "echo",
                    "inputs": {"message": "building"},
                    "outputs": ["log"],
                    "preconditions": ["env=prod"],
                    "effects": ["built=true"],
                    "depends_on": [],
                    "budget_tokens": 100,
                    "cost_money": 2.5,
                    "requires_approval": False,
                    "approver": "",
                    "status": "pending",
                },
                {
                    "step_id": "ship",
                    "name": "Ship",
                    "tool": "noop",
                    "inputs": {},
                    "outputs": [],
                    "preconditions": [],
                    "effects": [],
                    "depends_on": ["build"],
                    "budget_tokens": 0,
                    "cost_money": 10.0,
                    "requires_approval": True,
                    "approver": "release-manager",
                    "status": "pending",
                },
            ],
        }
        assert self._golden_plan().to_dict() == expected

    def test_roundtrip_is_lossless(self):
        plan = self._golden_plan()
        restored = Plan.from_dict(plan.to_dict())
        assert restored.to_dict() == plan.to_dict()
        assert restored.digest() == plan.digest()
        assert restored.steps[1].requires_approval is True
        assert restored.steps[0].effects == ["built=true"]
