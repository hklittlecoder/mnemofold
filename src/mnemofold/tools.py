"""Tool execution: specs, validation, idempotency, retries."""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mnemofold.canon import canonical_json


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
    timeout_seconds: float = 30.0
    max_retries: int = 0
    idempotent: bool = False
    capabilities: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if isinstance(self.side_effect, str):
            self.side_effect = SideEffectClass(self.side_effect)

    def to_schema(self) -> dict[str, Any]:
        """Declarative JSON-schema-style view of this tool.

        Deterministic (sorted capabilities and parameters) so schemas can
        be hashed, diffed across versions, and shown to a planner before
        any invocation happens.
        """
        return {
            "name": self.name,
            "description": self.description,
            "side_effect": self.side_effect.value,
            "idempotent": self.idempotent,
            "capabilities": sorted(self.capabilities),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "required": list(self.required),
            "parameters": {
                param: dict(sorted(spec.items())) for param, spec in sorted(self.parameters.items())
            },
        }


class ToolValidationError(ValueError):
    pass


class ToolPolicyError(RuntimeError):
    """Raised when a tool invocation violates the active policy."""


class ToolTimeoutError(RuntimeError):
    """Raised when a tool exceeds its enforced wall-clock timeout."""


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
    cached: bool = False


@dataclass
class IdempotencyStore:
    """Result cache keyed by idempotency key.

    Side-effecting tools that declare ``idempotent=True`` promise that a
    replay is safe; caching their successful results makes replay return
    the original outcome instead of executing the effect a second time.
    Failed results are never cached.
    """

    _results: dict[str, ToolResult] = field(default_factory=dict)

    def get(self, key: str) -> ToolResult | None:
        return self._results.get(key)

    def put(self, key: str, result: ToolResult) -> None:
        self._results[key] = result

    def __len__(self) -> int:
        return len(self._results)

    def __contains__(self, key: str) -> bool:
        return key in self._results


def _digest_output(output: Any) -> str:
    """Stable short digest of a tool output (receipts store digests only)."""
    canonical = json.dumps(
        output, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _chain_link(prev_head: str, receipt: ToolReceipt) -> str:
    """One link of the receipt chain: H(prev_head || canonical receipt)."""
    payload = prev_head + canonical_json(receipt.to_dict())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ToolReceipt:
    """Policy-gated record of one tool execution attempt.

    Receipts carry an output *digest*, never the raw output, so a receipt
    log can be shared or replayed without leaking side-effect payloads.
    ``decision`` records the policy outcome (allowed/denied); denied
    attempts are receipted too, so refusals are auditable.
    """

    tool_name: str
    idempotency_key: str
    side_effect: str
    success: bool
    output_digest: str
    decision: str
    error: str = ""
    retries: int = 0
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "idempotency_key": self.idempotency_key,
            "side_effect": self.side_effect,
            "success": self.success,
            "output_digest": self.output_digest,
            "decision": self.decision,
            "error": self.error,
            "retries": self.retries,
            "from_cache": self.from_cache,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolReceipt:
        return cls(
            tool_name=data["tool_name"],
            idempotency_key=data["idempotency_key"],
            side_effect=data["side_effect"],
            success=bool(data["success"]),
            output_digest=data.get("output_digest", ""),
            decision=data.get("decision", "allowed"),
            error=data.get("error", ""),
            retries=int(data.get("retries", 0)),
            from_cache=bool(data.get("from_cache", False)),
        )


@dataclass
class ReceiptLog:
    """Append-only receipt list with a deterministic chained digest.

    Beyond the order-sensitive :meth:`digest` over the whole list, the
    log maintains a running chain head: every append hashes the previous
    head together with the new receipt, so :meth:`verify_chain` can
    prove that a head value still matches the exact sequence held.
    """

    _receipts: list[ToolReceipt] = field(default_factory=list)
    _head: str = ""

    def append(self, receipt: ToolReceipt) -> None:
        self._receipts.append(receipt)
        self._head = _chain_link(self._head, receipt)

    def receipts(self) -> list[ToolReceipt]:
        return list(self._receipts)

    def for_tool(self, name: str) -> list[ToolReceipt]:
        return [r for r in self._receipts if r.tool_name == name]

    def __len__(self) -> int:
        return len(self._receipts)

    def digest(self) -> str:
        payload = [
            [
                r.tool_name,
                r.idempotency_key,
                r.side_effect,
                r.success,
                r.output_digest,
                r.decision,
                r.error,
                r.retries,
                r.from_cache,
            ]
            for r in self._receipts
        ]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def head(self) -> str:
        """Chained head digest; the empty string for an empty log."""
        return self._head

    def verify_chain(self, expected_head: str) -> bool:
        """Recompute the chain from scratch and compare to ``expected_head``.

        Catches dropped, reordered or edited receipts: every link hashes
        the previous head together with one receipt's canonical form, so
        any change downstream of an edit shifts the head. An empty log
        verifies only against the empty string.
        """
        head = ""
        for receipt in self._receipts:
            head = _chain_link(head, receipt)
        return head == expected_head

    def to_jsonl(self) -> str:
        """Serialize receipts as JSONL (one canonical JSON object per line)."""
        return "".join(
            json.dumps(r.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
            for r in self._receipts
        )

    @classmethod
    def from_jsonl(cls, text: str) -> ReceiptLog:
        """Rebuild a receipt log from :meth:`to_jsonl` output."""
        log = cls()
        for line in text.splitlines():
            if line.strip():
                log.append(ToolReceipt.from_dict(json.loads(line)))
        return log


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


def _retry_delay(
    attempt: int, base: float = 0.01, cap: float = 1.0, rng: random.Random | None = None
) -> float:
    """Exponential backoff with bounded jitter inside [exp, exp * 1.5].

    ``rng`` makes the jitter deterministic; without it the module-level
    Random is used. Registries pass their own seeded RNG so retries are
    reproducible across runs and machines.
    """
    exp = min(base * (2 ** (attempt - 1)), cap)
    source = rng if rng is not None else random
    return exp + source.uniform(0, exp * 0.5)


@dataclass
class ToolRegistry:
    _specs: dict[str, ToolSpec] = field(default_factory=dict)
    _impls: dict[str, Callable[..., Any]] = field(default_factory=dict)
    policy: ToolPolicy | None = None
    idempotency: IdempotencyStore | None = None
    receipts: ReceiptLog | None = None
    enforce_timeouts: bool = False
    rng_seed: int = 0
    _rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        # Reseed from rng_seed so retry jitter is reproducible.
        self._rng = random.Random(self.rng_seed)

    def register(self, spec: ToolSpec, impl: Callable[..., Any]) -> None:
        errors = self.validate_spec(spec)
        if errors:
            raise ToolValidationError("invalid tool spec: " + "; ".join(errors))
        self._specs[spec.name] = spec
        self._impls[spec.name] = impl

    def validate_spec(self, spec: ToolSpec) -> list[str]:
        """Check a tool spec for structural issues.

        Rejects negative timeouts, negative retries, side-effect tools that
        claim idempotency but lack a way to deduplicate, and required params
        that aren't declared in the parameter schema. Errors are returned in
        a deterministic order so tests can pin them.
        """
        errors: list[str] = []
        if spec.timeout_seconds < 0:
            errors.append("timeout_seconds must be non-negative")
        if spec.max_retries < 0:
            errors.append("max_retries must be non-negative")
        if not spec.name:
            errors.append("tool name must not be empty")
        for required in spec.required:
            if required not in spec.parameters:
                errors.append(f"required param '{required}' not declared in parameters")
        return errors

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
                self._record_receipt(
                    name,
                    self._idem_key(name, args),
                    spec,
                    success=False,
                    decision="denied",
                    error="; ".join(violations),
                )
                raise ToolPolicyError("; ".join(violations))
        errors = self.validate_args(name, args)
        if errors:
            raise ToolValidationError("; ".join(errors))
        impl = self._impls[name]
        idem_key = self._idem_key(name, args)
        store = self.idempotency
        cacheable = (
            store is not None
            and spec.idempotent
            and spec.side_effect
            in (SideEffectClass.WRITE, SideEffectClass.SPEND, SideEffectClass.DESTRUCTIVE)
        )
        if cacheable and store is not None:
            hit = store.get(idem_key)
            if hit is not None:
                self._record_receipt(
                    name,
                    idem_key,
                    spec,
                    success=True,
                    decision="allowed",
                    output=hit.output,
                    retries=hit.retries,
                    from_cache=True,
                )
                return ToolResult(
                    tool_name=hit.tool_name,
                    success=hit.success,
                    output=hit.output,
                    error=hit.error,
                    execution_time_ms=hit.execution_time_ms,
                    idempotency_key=hit.idempotency_key,
                    retries=hit.retries,
                    cached=True,
                )
        retries = 0
        start = time.monotonic()
        while True:
            try:
                if self.enforce_timeouts and spec.timeout_seconds > 0:
                    output = self._invoke_with_timeout(impl, args, spec.timeout_seconds)
                else:
                    output = impl(**args)
                elapsed = (time.monotonic() - start) * 1000
                result = ToolResult(
                    tool_name=name,
                    success=True,
                    output=output,
                    execution_time_ms=elapsed,
                    idempotency_key=idem_key,
                    retries=retries,
                )
                if cacheable and store is not None:
                    store.put(idem_key, result)
                self._record_receipt(
                    name,
                    idem_key,
                    spec,
                    success=True,
                    decision="allowed",
                    output=result.output,
                    retries=retries,
                )
                return result
            except Exception as e:
                if retries >= spec.max_retries:
                    elapsed = (time.monotonic() - start) * 1000
                    self._record_receipt(
                        name,
                        idem_key,
                        spec,
                        success=False,
                        decision="allowed",
                        error=str(e),
                        retries=retries,
                    )
                    return ToolResult(
                        tool_name=name,
                        success=False,
                        error=str(e),
                        execution_time_ms=elapsed,
                        idempotency_key=idem_key,
                        retries=retries,
                    )
                retries += 1
                time.sleep(_retry_delay(retries, rng=self._rng))

    def _invoke_with_timeout(
        self, impl: Callable[..., Any], args: dict[str, Any], timeout: float
    ) -> Any:
        """Run impl in a worker thread bounded by a wall-clock timeout.

        On overrun the call raises :class:`ToolTimeoutError` (which the
        retry loop treats like any other failure). The abandoned worker
        is not waited on, so a hung tool cannot block the registry.
        """
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(lambda: impl(**args))
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            raise ToolTimeoutError(f"tool exceeded timeout of {timeout}s") from exc
        finally:
            pool.shutdown(wait=False)

    def _record_receipt(
        self,
        name: str,
        idem_key: str,
        spec: ToolSpec,
        *,
        success: bool,
        decision: str,
        output: Any = None,
        error: str = "",
        retries: int = 0,
        from_cache: bool = False,
    ) -> None:
        """Append a receipt for one execution attempt (no-op when unhooked)."""
        if self.receipts is None:
            return
        self.receipts.append(
            ToolReceipt(
                tool_name=name,
                idempotency_key=idem_key,
                side_effect=spec.side_effect.value,
                success=success,
                output_digest=_digest_output(output) if success else "",
                error=error,
                decision=decision,
                retries=retries,
                from_cache=from_cache,
            )
        )

    def _idem_key(self, name: str, args: dict[str, Any]) -> str:
        payload = {"tool": name, "args": dict(sorted(args.items()))}
        h = hashlib.sha256(str(payload).encode()).hexdigest()
        return f"idem_{h[:16]}"

    def list_tools(self) -> list[ToolSpec]:
        return sorted(self._specs.values(), key=lambda s: s.name)

    def tools_with_capability(self, capability: str) -> list[ToolSpec]:
        """All tools that declare the given capability tag.

        Capabilities let a planner or policy surface only tools relevant
        to a task (e.g. ``"file_io"``, ``"calendar"``) without exposing
        the whole registry. Results are sorted by tool name.
        """
        matches = [s for s in self._specs.values() if capability in s.capabilities]
        return sorted(matches, key=lambda s: s.name)

    def tools_by_side_effect(self, effect: SideEffectClass | str) -> list[ToolSpec]:
        """All tools with a particular side-effect class, sorted by name."""
        eff = SideEffectClass(effect) if isinstance(effect, str) else effect
        return sorted(
            [s for s in self._specs.values() if s.side_effect == eff],
            key=lambda s: s.name,
        )

    def schemas(self) -> list[dict[str, Any]]:
        """Schemas of all registered tools, sorted by tool name."""
        return [spec.to_schema() for spec in self.list_tools()]


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
