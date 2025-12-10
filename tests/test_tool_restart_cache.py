"""A persisted idempotency store must serve cache hits after a restart.

The registry derives idempotency keys from tool name and arguments, so
a store written by one registry instance must short-circuit the same
call on a fresh instance — that is the whole point of persisting it.
"""

from mnemofold.tools import IdempotencyStore, SideEffectClass, ToolRegistry, ToolSpec

SPEC = ToolSpec(
    name="send_mail",
    description="send a mail (test stub)",
    side_effect=SideEffectClass.WRITE,
    idempotent=True,
    parameters={"to": {"type": "string"}},
    required=["to"],
)


def build_registry(store: IdempotencyStore, calls: list[str]) -> ToolRegistry:
    registry = ToolRegistry(idempotency=store)

    def send(to: str) -> dict[str, str]:
        calls.append(to)
        return {"sent_to": to}

    registry.register(SPEC, send)
    return registry


class TestCrossRestartCache:
    def test_reload_serves_cached_result_without_side_effect(self, tmp_path):
        calls_first: list[str] = []
        store = IdempotencyStore()
        first = build_registry(store, calls_first)
        r1 = first.invoke("send_mail", {"to": "ana@corp.example"})
        assert r1.success
        assert not r1.cached
        assert calls_first == ["ana@corp.example"]
        store.save(tmp_path / "idem.jsonl")

        calls_second: list[str] = []
        reloaded = IdempotencyStore.load(tmp_path / "idem.jsonl")
        second = build_registry(reloaded, calls_second)
        r2 = second.invoke("send_mail", {"to": "ana@corp.example"})
        assert r2.success
        assert r2.cached
        assert r2.output == r1.output
        assert calls_second == []  # the side effect did not run again

    def test_different_args_still_execute_after_reload(self, tmp_path):
        store = IdempotencyStore()
        first = build_registry(store, [])
        first.invoke("send_mail", {"to": "ana@corp.example"})
        store.save(tmp_path / "idem.jsonl")

        calls: list[str] = []
        second = build_registry(IdempotencyStore.load(tmp_path / "idem.jsonl"), calls)
        r = second.invoke("send_mail", {"to": "bo@corp.example"})
        assert r.success
        assert not r.cached
        assert calls == ["bo@corp.example"]
