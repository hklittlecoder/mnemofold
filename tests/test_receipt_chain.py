"""Chained-digest verification for the tool receipt log."""

from mnemofold.tools import ReceiptLog, ToolReceipt


def make_receipt(tool: str, key: str, success: bool = True) -> ToolReceipt:
    return ToolReceipt(
        tool_name=tool,
        idempotency_key=key,
        side_effect="write",
        success=success,
        output_digest="abc123",
        decision="allowed",
    )


class TestReceiptChain:
    def test_empty_log_head_is_empty_string(self):
        log = ReceiptLog()
        assert log.head() == ""
        assert log.verify_chain("")
        assert not log.verify_chain("0" * 64)

    def test_head_changes_with_every_append(self):
        log = ReceiptLog()
        heads = [log.head()]
        for i in range(3):
            log.append(make_receipt("send", f"k{i}"))
            heads.append(log.head())
        assert len(set(heads)) == 4

    def test_verify_chain_accepts_own_head(self):
        log = ReceiptLog()
        log.append(make_receipt("send", "k1"))
        log.append(make_receipt("fetch", "k2", success=False))
        assert log.verify_chain(log.head())

    def test_verify_chain_rejects_stale_head(self):
        log = ReceiptLog()
        log.append(make_receipt("send", "k1"))
        stale = log.head()
        log.append(make_receipt("send", "k2"))
        assert not log.verify_chain(stale)

    def test_reordered_receipts_change_head(self):
        a = ReceiptLog()
        a.append(make_receipt("send", "k1"))
        a.append(make_receipt("fetch", "k2"))
        b = ReceiptLog()
        b.append(make_receipt("fetch", "k2"))
        b.append(make_receipt("send", "k1"))
        assert a.head() != b.head()

    def test_jsonl_roundtrip_preserves_chain(self):
        log = ReceiptLog()
        for i in range(4):
            log.append(make_receipt(f"tool{i}", f"k{i}"))
        rebuilt = ReceiptLog.from_jsonl(log.to_jsonl())
        assert rebuilt.head() == log.head()
        assert rebuilt.verify_chain(log.head())

    def test_independent_logs_agree_on_head(self):
        x, y = ReceiptLog(), ReceiptLog()
        for log in (x, y):
            log.append(make_receipt("send", "same"))
            log.append(make_receipt("send", "same2"))
        assert x.head() == y.head()

    def test_editing_a_receipt_shifts_the_head(self):
        honest = ReceiptLog()
        honest.append(make_receipt("send", "k1", success=True))
        head = honest.head()
        tampered = ReceiptLog()
        tampered.append(make_receipt("send", "k1", success=False))
        assert tampered.head() != head
        assert not tampered.verify_chain(head)
