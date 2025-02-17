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

    def __post_init__(self):
        if isinstance(self.side_effect, str):
            self.side_effect = SideEffectClass(self.side_effect)


class ToolValidationError(ValueError):
    pass


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    success: bool
    output: Any = None
    error: str = ""
    execution_time_ms: float = 0.0
    idempotency_key: str = ""
    retries: int = 0


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _check_type(value, type_name):
    expected = _TYPE_MAP.get(type_name)
    if expected is None:
        return True
    if type_name == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _retry_delay(attempt, base=0.01, cap=1.0):
    exp = min(base * (2 ** (attempt - 1)), cap)
    return exp + random.uniform(0, exp * 0.5)


@dataclass
class ToolRegistry:
    _specs: dict[str, ToolSpec] = field(default_factory=dict)
    _impls: dict[str, Callable] = field(default_factory=dict)

    def register(self, spec, impl):
        self._specs[spec.name] = spec
        self._impls[spec.name] = impl

    def get_spec(self, name):
        return self._specs.get(name)

    def validate_args(self, name, args):
        spec = self._specs.get(name)
        if spec is None:
            return [f"unknown tool: {name}"]
        errors = []
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

    def invoke(self, name, args):
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(tool_name=name, success=False, error=f"unknown tool: {name}")
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

    def _idem_key(self, name, args):
        payload = {"tool": name, "args": dict(sorted(args.items()))}
        h = hashlib.sha256(str(payload).encode()).hexdigest()
        return f"idem_{h[:16]}"

    def list_tools(self):
        return sorted(self._specs.values(), key=lambda s: s.name)


def _echo_impl(message=""):
    return message


def _noop_impl():
    return {"status": "ok"}


def build_default_registry():
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
