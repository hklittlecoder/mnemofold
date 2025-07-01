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
