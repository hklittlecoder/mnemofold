"""Tool execution: specs, validation, idempotency, retries."""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SideEffectClass(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    SPEND = "spend"


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    side_effect: SideEffectClass = SideEffectClass.NONE
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    timeout_seconds: int = 30
    max_retries: int = 0
    idempotent: bool = False
    capabilities: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if isinstance(self.side_effect, str):
            self.side_effect = SideEffectClass(self.side_effect)


class ToolValidationError(ValueError):
    pass


class ToolPolicyError(RuntimeError):
    """Raised when a tool invocation violates the active policy."""


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """Declarative gate applied before any tool execution.

    * ``allowed_capabilities``: when non-empty, the tool must declare at
      least one of them;
    * ``denied_side_effects``: tools in these classes are refused;
    * ``require_idempotent_for``: side-effect classes whose tools must be
      marked idempotent so replays stay safe.

    Defaults refuse destructive and spend-class tools outright: an
    assistant should need an explicit policy change to reach them.
    """

    allowed_capabilities: frozenset[str] = frozenset()
    denied_side_effects: frozenset[str] = frozenset(
        {SideEffectClass.DESTRUCTIVE.value, SideEffectClass.SPEND.value}
    )
    require_idempotent_for: frozenset[str] = frozenset(
        {
            SideEffectClass.WRITE.value,
            SideEffectClass.SPEND.value,
            SideEffectClass.DESTRUCTIVE.value,
        }
    )

    def violations(self, spec: ToolSpec) -> list[str]:
        """All policy violations for a spec, in a stable order."""
        found: list[str] = []
        if spec.side_effect.value in self.denied_side_effects:
            found.append(f"side effect '{spec.side_effect.value}' is denied by policy")
        if self.allowed_capabilities and not (
            set(spec.capabilities) & set(self.allowed_capabilities)
        ):
            found.append(f"tool lacks required capabilities: {sorted(self.allowed_capabilities)}")
        if spec.side_effect.value in self.require_idempotent_for and not spec.idempotent:
            found.append(f"tool with side effect '{spec.side_effect.value}' must be idempotent")
        return found


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    success: bool
    output: Any = None
    error: str = ""
    execution_time_ms: float = 0.0
    idempotency_key: str = ""
    retries: int = 0


_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _check_type(value: Any, type_name: str) -> bool:
    expected = _TYPE_MAP.get(type_name)
    if expected is None:
        return True
    if type_name == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _retry_delay(attempt: int, base: float = 0.01, cap: float = 1.0) -> float:
    exp = min(base * (2 ** (attempt - 1)), cap)
    return exp + random.uniform(0, exp * 0.5)


@dataclass
class ToolRegistry:
    _specs: dict[str, ToolSpec] = field(default_factory=dict)
    _impls: dict[str, Callable[..., Any]] = field(default_factory=dict)
    policy: ToolPolicy | None = None

    def register(self, spec: ToolSpec, impl: Callable[..., Any]) -> None:
        self._specs[spec.name] = spec
        self._impls[spec.name] = impl

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def validate_args(self, name: str, args: dict[str, Any]) -> list[str]:
        spec = self._specs.get(name)
        if spec is None:
            return [f"unknown tool: {name}"]
        errors: list[str] = []
        for param in spec.required:
            if param not in args:
                errors.append(f"missing required parameter: {param}")
        for param, value in args.items():
            if param in spec.parameters:
                expected = spec.parameters[param].get("type", "")
                if expected and not _check_type(value, expected):
                    errors.append(
                        f"parameter '{param}' expected {expected}, got {type(value).__name__}"
                    )
        return errors

    def invoke(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(tool_name=name, success=False, error=f"unknown tool: {name}")
        if self.policy is not None:
            violations = self.policy.violations(spec)
            if violations:
                raise ToolPolicyError("; ".join(violations))
        errors = self.validate_args(name, args)
        if errors:
            raise ToolValidationError("; ".join(errors))
        impl = self._impls[name]
        idem_key = self._idem_key(name, args)
        retries = 0
        start = time.monotonic()
        while True:
            try:
                output = impl(**args)
                elapsed = (time.monotonic() - start) * 1000
                return ToolResult(
                    tool_name=name,
                    success=True,
                    output=output,
                    execution_time_ms=elapsed,
                    idempotency_key=idem_key,
                    retries=retries,
                )
            except Exception as e:
                if retries >= spec.max_retries:
                    elapsed = (time.monotonic() - start) * 1000
                    return ToolResult(
                        tool_name=name,
                        success=False,
                        error=str(e),
                        execution_time_ms=elapsed,
                        idempotency_key=idem_key,
                        retries=retries,
                    )
                retries += 1
                time.sleep(_retry_delay(retries))

    def _idem_key(self, name: str, args: dict[str, Any]) -> str:
        payload = {"tool": name, "args": dict(sorted(args.items()))}
        h = hashlib.sha256(str(payload).encode()).hexdigest()
        return f"idem_{h[:16]}"

    def list_tools(self) -> list[ToolSpec]:
        return sorted(self._specs.values(), key=lambda s: s.name)


def _echo_impl(message: str = "") -> str:
    return message


def _noop_impl() -> dict[str, str]:
    return {"status": "ok"}


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="echo",
            description="Echo message",
            side_effect=SideEffectClass.NONE,
            parameters={"message": {"type": "string"}},
            required=["message"],
            idempotent=True,
        ),
        _echo_impl,
    )
    reg.register(
        ToolSpec(
            name="noop", description="No-op", side_effect=SideEffectClass.NONE, idempotent=True
        ),
        _noop_impl,
    )
    return reg
