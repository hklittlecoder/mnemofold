"""Plan file persistence: digests, validation and schema guards."""

import pytest

from mnemofold.persist import PersistError, write_envelope
from mnemofold.plan import Plan, PlanStep, validate_plan


def make_plan() -> Plan:
    return Plan(
        plan_id="plan-release",
        name="Release run",
        total_budget_tokens=5000,
        money_budget=10.0,
        steps=[
            PlanStep(
                step_id="s1",
                name="draft",
                tool="echo",
                inputs={"text": "draft"},
                outputs=["draft_out"],
                budget_tokens=1000,
                cost_money=1.5,
            ),
            PlanStep(
                step_id="s2",
                name="publish",
                tool="echo",
                inputs={"text": "publish"},
                depends_on=["s1"],
                requires_approval=True,
                approver="boss",
                budget_tokens=2000,
            ),
        ],
    )


class TestPlanPersist:
    def test_roundtrip_preserves_dict_and_digest(self, tmp_path):
        plan = make_plan()
        path = tmp_path / "plan.json"
        plan.save(path)
        loaded = Plan.load(path)
        assert loaded.to_dict() == plan.to_dict()
        assert loaded.digest() == plan.digest()

    def test_loaded_plan_still_validates(self, tmp_path):
        path = tmp_path / "plan.json"
        make_plan().save(path)
        result = validate_plan(Plan.load(path))
        assert result.valid, result.errors

    def test_step_details_survive(self, tmp_path):
        path = tmp_path / "plan.json"
        make_plan().save(path)
        loaded = Plan.load(path)
        s2 = next(s for s in loaded.steps if s.step_id == "s2")
        assert s2.depends_on == ["s1"]
        assert s2.requires_approval is True
        assert s2.approver == "boss"
        assert s2.budget_tokens == 2000
        assert loaded.money_budget == 10.0

    def test_save_bytes_are_deterministic(self, tmp_path):
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        make_plan().save(a)
        make_plan().save(b)
        assert a.read_bytes() == b.read_bytes()

    def test_load_rejects_wrong_version(self, tmp_path):
        path = tmp_path / "v2.json"
        write_envelope(path, "plan", make_plan().to_dict(), version=2)
        with pytest.raises(PersistError, match="schema_version"):
            Plan.load(path)

    def test_load_rejects_foreign_schema(self, tmp_path):
        path = tmp_path / "other.json"
        write_envelope(path, "bm25_index", {"docs": {}})
        with pytest.raises(PersistError, match="schema mismatch"):
            Plan.load(path)
