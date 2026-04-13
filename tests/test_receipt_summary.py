"""Receipt log summary aggregation."""

from mnemofold.tools import ReceiptLog, ToolReceipt


def receipt(
    tool: str,
    *,
    success: bool = True,
    decision: str = "allowed",
    key: str = "",
    cached: bool = False,
) -> ToolReceipt:
    return ToolReceipt(
        tool_name=tool,
        idempotency_key=key,
        side_effect="write",
        success=success,
        output_digest="d",
        decision=decision,
        from_cache=cached,
    )


class TestReceiptSummary:
    def test_empty_log_summarizes_to_zeros(self):
        summary = ReceiptLog().summary()
        assert summary["total"] == 0
        assert summary["by_tool"] == {}
        assert summary["by_decision"] == {}
        assert summary["successes"] == summary["failures"] == summary["cached"] == 0

    def test_counts_by_tool_and_decision(self):
        log = ReceiptLog()
        log.append(receipt("send", key="k1"))
        log.append(receipt("send", success=False, key="k2"))
        log.append(receipt("fetch", decision="denied", success=False))
        summary = log.summary()
        assert summary["total"] == 3
        assert summary["by_tool"] == {"fetch": 1, "send": 2}
        assert summary["by_decision"] == {"allowed": 2, "denied": 1}
        assert summary["successes"] == 1
        assert summary["failures"] == 2

    def test_cached_and_key_counts(self):
        log = ReceiptLog()
        log.append(receipt("send", key="k1"))
        log.append(receipt("send", key="k1", cached=True))
        summary = log.summary()
        assert summary["cached"] == 1
        assert summary["unique_idempotency_keys"] == 1

    def test_summary_is_deterministic(self):
        log = ReceiptLog()
        log.append(receipt("b"))
        log.append(receipt("a"))
        assert log.summary() == log.summary()
        assert list(log.summary()["by_tool"]) == ["a", "b"]
