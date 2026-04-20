"""Timeout enforcement: slow tools fail bounded, fast tools pass through."""

import time

from mnemofold.tools import ReceiptLog, ToolRegistry, ToolSpec


def slow_registry(enforce: bool, max_retries: int = 1) -> ToolRegistry:
    registry = ToolRegistry(receipts=ReceiptLog(), enforce_timeouts=enforce, rng_seed=7)
    registry.register(
        ToolSpec(
            name="slow",
            description="sleeps longer than its timeout",
            timeout_seconds=0.05,
            max_retries=max_retries,
        ),
        lambda: time.sleep(0.4) or "late",
    )
    registry.register(
        ToolSpec(name="fast", description="returns immediately", timeout_seconds=5.0),
        lambda: "ok",
    )
    return registry


class TestTimeouts:
    def test_slow_tool_fails_with_bounded_retries(self):
        registry = slow_registry(enforce=True, max_retries=1)
        result = registry.invoke("slow", {})
        assert result.success is False
        assert result.retries == 1
        assert result.error

    def test_failure_is_receipted(self):
        registry = slow_registry(enforce=True, max_retries=0)
        registry.invoke("slow", {})
        summary = registry.receipts.summary()
        assert summary["total"] == 1
        assert summary["failures"] == 1

    def test_fast_tool_unaffected(self):
        registry = slow_registry(enforce=True)
        result = registry.invoke("fast", {})
        assert result.success is True
        assert result.output == "ok"

    def test_enforcement_disabled_lets_slow_tool_finish(self):
        registry = slow_registry(enforce=False)
        result = registry.invoke("slow", {})
        assert result.success is True
        assert result.output == "late"

    def test_zero_retries_means_single_attempt(self):
        registry = slow_registry(enforce=True, max_retries=0)
        result = registry.invoke("slow", {})
        assert result.success is False
        assert result.retries == 0
