"""Policy denials must raise AND leave a receipt — refusals are auditable."""

import pytest

from mnemofold.tools import (
    ReceiptLog,
    SideEffectClass,
    ToolPolicy,
    ToolPolicyError,
    ToolRegistry,
    ToolSpec,
)


def build_registry() -> tuple[ToolRegistry, list[str]]:
    calls: list[str] = []
    registry = ToolRegistry(receipts=ReceiptLog(), policy=ToolPolicy())
    registry.register(
        ToolSpec(
            name="wipe",
            description="destructive stub",
            side_effect=SideEffectClass.DESTRUCTIVE,
            idempotent=True,
        ),
        lambda: calls.append("wipe"),
    )
    registry.register(
        ToolSpec(
            name="write_naive",
            description="write without idempotency",
            side_effect=SideEffectClass.WRITE,
            idempotent=False,
            parameters={"path": {"type": "string"}},
            required=["path"],
        ),
        lambda path: calls.append(path),
    )
    return registry, calls


class TestPolicyDenials:
    def test_denied_side_effect_raises_and_receipts(self):
        registry, calls = build_registry()
        with pytest.raises(ToolPolicyError):
            registry.invoke("wipe", {})
        assert calls == []  # implementation never ran
        summary = registry.receipts.summary()
        assert summary["by_decision"] == {"denied": 1}
        assert summary["successes"] == 0

    def test_non_idempotent_write_is_denied(self):
        registry, calls = build_registry()
        with pytest.raises(ToolPolicyError, match="must be idempotent"):
            registry.invoke("write_naive", {"path": "/tmp/x"})
        assert calls == []
        receipts = registry.receipts.receipts()
        assert len(receipts) == 1
        assert "idempotent" in receipts[0].error

    def test_denial_receipt_carries_violation_reason(self):
        registry, _ = build_registry()
        with pytest.raises(ToolPolicyError):
            registry.invoke("wipe", {})
        record = registry.receipts.receipts()[0]
        assert record.decision == "denied"
        assert record.tool_name == "wipe"
        assert "denied by policy" in record.error
        assert record.success is False

    def test_allowed_policy_change_flows_through(self):
        calls: list[str] = []
        registry = ToolRegistry(
            receipts=ReceiptLog(),
            policy=ToolPolicy(denied_side_effects=frozenset(), require_idempotent_for=frozenset()),
        )
        registry.register(
            ToolSpec(
                name="wipe", description="now allowed", side_effect=SideEffectClass.DESTRUCTIVE
            ),
            lambda: calls.append("wipe"),
        )
        result = registry.invoke("wipe", {})
        assert result.success
        assert calls == ["wipe"]
        assert registry.receipts.summary()["by_decision"] == {"allowed": 1}
