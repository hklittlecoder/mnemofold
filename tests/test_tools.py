"""Tests for tools."""

from __future__ import annotations

import random
import time

import pytest

from mnemofold.tools import (
    IdempotencyStore,
    SideEffectClass,
    ToolPolicy,
    ToolPolicyError,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
    _retry_delay,
    build_default_registry,
)


def test_default_echo():
    reg = build_default_registry()
    r = reg.invoke("echo", {"message": "hi"})
    assert r.success and r.output == "hi"


def test_default_noop():
    reg = build_default_registry()
    r = reg.invoke("noop", {})
    assert r.success and r.output["status"] == "ok"


def test_validate_missing_required():
    reg = build_default_registry()
    errors = reg.validate_args("echo", {})
    assert any("missing" in e for e in errors)


def test_validate_type_error():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="t", description="d", parameters={"x": {"type": "integer"}}),
        lambda x: x,
    )
    errors = reg.validate_args("t", {"x": "notnum"})
    assert len(errors) == 1


def test_invoke_invalid_raises():
    reg = build_default_registry()
    with pytest.raises(ToolValidationError):
        reg.invoke("echo", {})


def test_idempotency_key_stable():
    reg = build_default_registry()
    k1 = reg._idem_key("echo", {"message": "a"})
    k2 = reg._idem_key("echo", {"message": "a"})
    assert k1 == k2


def test_unknown_tool():
    reg = ToolRegistry()
    r = reg.invoke("nope", {})
    assert not r.success


def test_list_tools():
    reg = build_default_registry()
    assert len(reg.list_tools()) >= 2


class TestToolPolicy:
    def _registry(self, policy: ToolPolicy | None = None) -> ToolRegistry:
        registry = ToolRegistry(policy=policy)
        registry.register(
            ToolSpec(
                name="read_doc",
                description="read",
                side_effect=SideEffectClass.READ,
                capabilities={"docs"},
                parameters={"doc": {"type": "string"}},
                required=["doc"],
            ),
            lambda doc: f"read {doc}",
        )
        registry.register(
            ToolSpec(
                name="write_doc",
                description="write",
                side_effect=SideEffectClass.WRITE,
                capabilities={"docs"},
                idempotent=True,
                parameters={"doc": {"type": "string"}},
                required=["doc"],
            ),
            lambda doc: f"wrote {doc}",
        )
        registry.register(
            ToolSpec(
                name="delete_all",
                description="danger",
                side_effect=SideEffectClass.DESTRUCTIVE,
                idempotent=True,
            ),
            lambda: "gone",
        )
        registry.register(
            ToolSpec(
                name="unsafe_write",
                description="write without idempotency",
                side_effect=SideEffectClass.WRITE,
            ),
            lambda: "x",
        )
        return registry

    def test_no_policy_allows_everything(self):
        assert self._registry().invoke("delete_all", {}).success

    def test_default_policy_denies_destructive(self):
        with pytest.raises(ToolPolicyError, match="denied by policy"):
            self._registry(ToolPolicy()).invoke("delete_all", {})

    def test_default_policy_requires_idempotent_writes(self):
        with pytest.raises(ToolPolicyError, match="must be idempotent"):
            self._registry(ToolPolicy()).invoke("unsafe_write", {})

    def test_default_policy_allows_reads_and_idempotent_writes(self):
        registry = self._registry(ToolPolicy())
        assert registry.invoke("read_doc", {"doc": "a"}).success
        assert registry.invoke("write_doc", {"doc": "a"}).success

    def test_capability_gate(self):
        policy = ToolPolicy(
            allowed_capabilities=frozenset({"docs"}), denied_side_effects=frozenset()
        )
        registry = self._registry(policy)
        assert registry.invoke("read_doc", {"doc": "a"}).success
        with pytest.raises(ToolPolicyError, match="capabilities"):
            registry.invoke("delete_all", {})

    def test_violations_enumerate_every_problem(self):
        spec = ToolSpec(name="spend", description="", side_effect=SideEffectClass.SPEND)
        violations = ToolPolicy().violations(spec)
        assert len(violations) == 2
        assert any("denied" in v for v in violations)
        assert any("idempotent" in v for v in violations)

    def test_policy_checked_before_argument_validation(self):
        registry = self._registry(ToolPolicy())
        # missing required args AND denied side effect: policy fires first
        with pytest.raises(ToolPolicyError):
            registry.invoke("delete_all", {"unexpected": 1})


class TestIdempotencyCache:
    def _registry(self, with_store: bool = True):
        calls: list[str] = []

        def write_impl(key: str) -> str:
            calls.append(key)
            return f"wrote {key}"

        registry = ToolRegistry(idempotency=IdempotencyStore() if with_store else None)
        registry.register(
            ToolSpec(
                name="write",
                description="write",
                side_effect=SideEffectClass.WRITE,
                parameters={"key": {"type": "string"}},
                required=["key"],
                idempotent=True,
            ),
            write_impl,
        )
        registry.register(
            ToolSpec(
                name="read",
                description="read",
                side_effect=SideEffectClass.READ,
                parameters={"key": {"type": "string"}},
                required=["key"],
                idempotent=True,
            ),
            lambda key: f"read {key}",
        )
        return registry, calls

    def test_second_write_hits_cache(self):
        registry, calls = self._registry()
        first = registry.invoke("write", {"key": "a"})
        second = registry.invoke("write", {"key": "a"})
        assert first.cached is False
        assert second.cached is True
        assert second.output == first.output
        assert calls == ["a"]  # impl ran once
        assert first.idempotency_key == second.idempotency_key

    def test_different_args_do_not_collide(self):
        registry, calls = self._registry()
        registry.invoke("write", {"key": "a"})
        registry.invoke("write", {"key": "b"})
        assert calls == ["a", "b"]

    def test_reads_are_not_cached(self):
        registry, _ = self._registry()
        first = registry.invoke("read", {"key": "a"})
        second = registry.invoke("read", {"key": "a"})
        assert first.cached is False and second.cached is False

    def test_without_store_everything_executes(self):
        registry, calls = self._registry(with_store=False)
        registry.invoke("write", {"key": "a"})
        registry.invoke("write", {"key": "a"})
        assert calls == ["a", "a"]

    def test_store_tracks_entries(self):
        registry, _ = self._registry()
        registry.invoke("write", {"key": "a"})
        assert len(registry.idempotency) == 1
        assert registry.invoke("write", {"key": "a"}).idempotency_key in registry.idempotency


def _flaky_tool(registry: ToolRegistry, state: dict, fail_times: int) -> None:
    def impl() -> str:
        state["n"] += 1
        if state["n"] <= fail_times:
            raise RuntimeError("transient failure")
        return "ok"

    registry.register(ToolSpec(name="flaky", description="", max_retries=3), impl)


class TestRetryDeterminism:
    def test_seeded_delay_sequences_match(self):
        first = [_retry_delay(a, rng=random.Random(7)) for a in (1, 2, 3)]
        second = [_retry_delay(a, rng=random.Random(7)) for a in (1, 2, 3)]
        assert first == second

    def test_delay_stays_within_jitter_bounds(self):
        rng = random.Random(3)
        for attempt in range(1, 6):
            exp = min(0.01 * (2 ** (attempt - 1)), 1.0)
            delay = _retry_delay(attempt, rng=rng)
            assert exp <= delay <= exp * 1.5 + 1e-12

    def test_same_seed_registries_sleep_identically(self, monkeypatch):
        sleeps_a: list[float] = []
        sleeps_b: list[float] = []

        monkeypatch.setattr(time, "sleep", sleeps_a.append)
        registry_a = ToolRegistry(rng_seed=11)
        _flaky_tool(registry_a, {"n": 0}, fail_times=2)
        assert registry_a.invoke("flaky", {}).success

        monkeypatch.setattr(time, "sleep", sleeps_b.append)
        registry_b = ToolRegistry(rng_seed=11)
        _flaky_tool(registry_b, {"n": 0}, fail_times=2)
        assert registry_b.invoke("flaky", {}).success

        assert sleeps_a == sleeps_b
        assert len(sleeps_a) == 2

    def test_different_seeds_usually_differ(self):
        a = [_retry_delay(i, rng=random.Random(1)) for i in (1, 2, 3, 4)]
        b = [_retry_delay(i, rng=random.Random(2)) for i in (1, 2, 3, 4)]
        assert a != b


class TestToolInvocationEdges:
    def test_unknown_tool_returns_failed_result(self):
        result = ToolRegistry().invoke("ghost", {})
        assert result.success is False
        assert "unknown tool" in result.error

    def test_validate_args_reports_missing_and_unknown(self):
        registry = build_default_registry()
        assert registry.validate_args("echo", {}) == ["missing required parameter: message"]
        assert registry.validate_args("ghost", {}) == ["unknown tool: ghost"]

    def test_type_validation_rejects_bool_as_integer(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="n",
                description="",
                parameters={"count": {"type": "integer"}},
                required=["count"],
            ),
            lambda count: count,
        )
        errors = registry.validate_args("n", {"count": True})
        assert errors and "expected integer" in errors[0]
        assert registry.validate_args("n", {"count": 3}) == []

    def test_invoke_raises_validation_error(self):
        registry = build_default_registry()
        with pytest.raises(ToolValidationError):
            registry.invoke("echo", {})

    def test_retries_then_succeeds(self):
        registry = ToolRegistry(rng_seed=5)
        state = {"n": 0}
        _flaky_tool(registry, state, fail_times=2)
        result = registry.invoke("flaky", {})
        assert result.success is True
        assert result.retries == 2
        assert result.output == "ok"

    def test_exhausted_retries_report_failure(self):
        registry = ToolRegistry(rng_seed=5)
        state = {"n": 0}
        _flaky_tool(registry, state, fail_times=99)
        result = registry.invoke("flaky", {})
        assert result.success is False
        assert "transient failure" in result.error
        assert result.retries == 3  # max_retries

    def test_idempotency_key_ignores_arg_order(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="pair",
                description="",
                parameters={"a": {"type": "string"}, "b": {"type": "string"}},
            ),
            lambda a, b: a + b,
        )
        first = registry.invoke("pair", {"a": "x", "b": "y"})
        second = registry.invoke("pair", {"b": "y", "a": "x"})
        assert first.idempotency_key == second.idempotency_key

    def test_list_tools_sorted_by_name(self):
        registry = build_default_registry()
        assert [spec.name for spec in registry.list_tools()] == ["echo", "noop"]

    def test_default_registry_echo_roundtrip(self):
        result = build_default_registry().invoke("echo", {"message": "hello"})
        assert result.success and result.output == "hello"
