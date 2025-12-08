"""JSONL persistence for the tool idempotency cache."""

from datetime import datetime

from mnemofold.tools import IdempotencyStore, ToolResult


def make_result(name: str = "send", key: str = "k1", output: object = None) -> ToolResult:
    return ToolResult(
        tool_name=name,
        success=True,
        output={"sent": True} if output is None else output,
        idempotency_key=key,
        execution_time_ms=1.25,
        retries=1,
        cached=False,
    )


class TestToolResultDict:
    def test_roundtrip_preserves_fields(self):
        r = make_result(output={"a": [1, 2]})
        assert ToolResult.from_dict(r.to_dict()) == r

    def test_timing_is_quantized_at_serialization(self):
        r = make_result()
        r.execution_time_ms = 1.234567891
        assert r.to_dict()["execution_time_ms"] == 1.234568

    def test_from_dict_tolerates_missing_optional_keys(self):
        back = ToolResult.from_dict({"tool_name": "x", "success": False})
        assert back.output is None
        assert back.error == ""
        assert back.retries == 0


class TestIdempotencyPersistence:
    def test_jsonl_roundtrip(self):
        store = IdempotencyStore()
        store.put("k1", make_result(key="k1"))
        store.put("k2", make_result(name="fetch", key="k2", output=[1, 2]))
        rebuilt = IdempotencyStore.from_jsonl(store.to_jsonl())
        assert rebuilt.get("k1") == store.get("k1")
        assert rebuilt.get("k2") == store.get("k2")
        assert len(rebuilt) == 2

    def test_byte_determinism_regardless_of_put_order(self):
        a, b = IdempotencyStore(), IdempotencyStore()
        a.put("k1", make_result(key="k1"))
        a.put("k2", make_result(key="k2"))
        b.put("k2", make_result(key="k2"))
        b.put("k1", make_result(key="k1"))
        assert a.to_jsonl() == b.to_jsonl()

    def test_empty_store_serializes_to_empty_string(self):
        assert IdempotencyStore().to_jsonl() == ""
        assert len(IdempotencyStore.from_jsonl("")) == 0

    def test_save_load_file(self, tmp_path):
        path = tmp_path / "idem.jsonl"
        store = IdempotencyStore()
        store.put("k1", make_result(key="k1"))
        store.save(path)
        assert path.read_text(encoding="utf-8") == store.to_jsonl()
        assert IdempotencyStore.load(path).get("k1") == store.get("k1")

    def test_non_json_output_falls_back_to_str(self):
        store = IdempotencyStore()
        store.put("k1", make_result(key="k1", output=datetime(2026, 1, 1)))
        rebuilt = IdempotencyStore.from_jsonl(store.to_jsonl())
        assert rebuilt.get("k1").output == "2026-01-01 00:00:00"

    def test_from_jsonl_skips_blank_lines(self):
        store = IdempotencyStore()
        store.put("k1", make_result(key="k1"))
        padded = "\n" + store.to_jsonl() + "\n\n"
        assert len(IdempotencyStore.from_jsonl(padded)) == 1
