"""Crash-in-the-middle-of-append semantics for the trace recorder.

A torn final line must (a) make verification fail, (b) refuse resume
instead of silently chaining onto corrupt bytes, and (c) be repairable
by truncating back to the last complete line — after which recording
continues and the whole chain still verifies.
"""

import pytest

from mnemofold.replay import TraceReader, TraceRecorder


def write_two(path) -> list[str]:
    with TraceRecorder(path) as rec:
        rec.record_event("2026-03-01T09:00:00+00:00", {"a": 1})
        rec.record_event("2026-03-01T10:00:00+00:00", {"b": 2})
    return path.read_text(encoding="utf-8").splitlines()


class TestPartialWrite:
    def test_torn_line_fails_verify(self, tmp_path):
        p = tmp_path / "t.jsonl"
        lines = write_two(p)
        p.write_text("\n".join(lines) + "\n" + '{"hash": "abc", "ent', encoding="utf-8")
        assert not TraceReader(p).verify()

    def test_torn_line_blocks_resume(self, tmp_path):
        p = tmp_path / "t.jsonl"
        lines = write_two(p)
        p.write_text("\n".join(lines) + "\n" + '{"hash": "abc", "ent', encoding="utf-8")
        with pytest.raises(ValueError):
            TraceRecorder(p)

    def test_truncate_repair_then_continue(self, tmp_path):
        p = tmp_path / "t.jsonl"
        lines = write_two(p)
        p.write_text("\n".join(lines) + "\n" + '{"hash": "abc", "ent', encoding="utf-8")
        # repair: keep only complete lines
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert TraceReader(p).verify()
        with TraceRecorder(p) as rec:
            assert rec.count() == 2
            rec.record_decision("2026-03-01T11:00:00+00:00", {"c": 3})
        reader = TraceReader(p)
        assert reader.verify()
        assert reader.count() == 3

    def test_clean_file_resumes_without_repair(self, tmp_path):
        p = tmp_path / "t.jsonl"
        write_two(p)
        with TraceRecorder(p) as rec:
            assert rec.count() == 2
        assert TraceReader(p).verify()
