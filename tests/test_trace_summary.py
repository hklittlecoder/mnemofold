"""Trace summary statistics with a golden chain-head digest.

The golden head below is the exact SHA-256 chain produced by the five
scripted entries in ``write_trace`` (one per entry kind). Any change to
entry serialization or chain hashing moves the digest and fails here
deliberately.
"""

import pytest

from mnemofold.replay import TraceReader, TraceRecorder

GOLDEN_HEAD = "8a2e0979d61e8dc3c709cacd922a89daed0e1281fb799513aa1b0ac676beee86"
GENESIS = "0" * 64


def write_trace(path) -> None:
    with TraceRecorder(path) as rec:
        rec.record_event("2026-03-01T09:00:00+00:00", {"a": 1})
        rec.record_decision("2026-03-01T10:00:00+00:00", {"result": "ok"})
        rec.record_recall("2026-03-01T11:00:00+00:00", {"item_id": "m1"})
        rec.record_receipt("2026-03-01T12:00:00+00:00", {"action": "fold"})
        rec.checkpoint("2026-03-01T13:00:00+00:00", {"stage": "done"})


class TestTraceSummary:
    def test_counts_by_kind(self, tmp_path):
        p = tmp_path / "t.jsonl"
        write_trace(p)
        summary = TraceReader(p).summary()
        assert summary["entries"] == 5
        assert summary["by_kind"] == {
            "checkpoint": 1,
            "decision": 1,
            "event": 1,
            "recall": 1,
            "receipt": 1,
        }

    def test_golden_head_hash(self, tmp_path):
        p = tmp_path / "t.jsonl"
        write_trace(p)
        summary = TraceReader(p).summary()
        assert summary["head_hash"] == GOLDEN_HEAD
        assert summary["head_hash"] == TraceReader(p).head()[0]

    def test_empty_trace_summary(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        with TraceRecorder(p):
            pass
        assert TraceReader(p).summary() == {
            "entries": 0,
            "by_kind": {},
            "head_hash": GENESIS,
        }

    def test_tampered_trace_raises(self, tmp_path):
        p = tmp_path / "t.jsonl"
        write_trace(p)
        text = p.read_text(encoding="utf-8")
        p.write_text(text.replace('"result": "ok"', '"result": "tampered"'), encoding="utf-8")
        with pytest.raises(ValueError, match="hash mismatch"):
            TraceReader(p).summary()

    def test_truncated_trace_summarizes_the_prefix(self, tmp_path):
        p = tmp_path / "t.jsonl"
        write_trace(p)
        lines = p.read_text(encoding="utf-8").splitlines()
        p.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")
        summary = TraceReader(p).summary()
        assert summary["entries"] == 3
        assert "checkpoint" not in summary["by_kind"]
        assert summary["by_kind"] == {"event": 1, "decision": 1, "recall": 1}
