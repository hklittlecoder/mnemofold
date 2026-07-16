"""Golden bytes for a checkpointed trace file.

Four scripted entries (event, receipt, checkpoint, event) freeze the
line format and the SHA-256 chain, including the checkpoint's
``ckpt-<count>`` entry id. Resume behavior is asserted on the same
fixture: a recorder reopened over it continues the chain.
"""

from pathlib import Path

from mnemofold.replay import TraceReader, TraceRecorder

FIXTURE = Path(__file__).parent / "fixtures" / "trace_checkpoint_golden.jsonl"


def write_scripted(path) -> None:
    with TraceRecorder(path) as rec:
        rec.record_event("2026-03-01T09:00:00+00:00", {"a": 1})
        rec.record_receipt("2026-03-01T09:05:00+00:00", {"action": "fold", "merged": 2})
        rec.checkpoint("2026-03-01T09:10:00+00:00", {"stage": "fold"})
        rec.record_event("2026-03-01T09:15:00+00:00", {"b": 2})


class TestTraceGolden:
    def test_scripted_trace_matches_golden_bytes(self, tmp_path):
        path = tmp_path / "trace.jsonl"
        write_scripted(path)
        assert path.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    def test_golden_verifies_and_summarizes(self):
        reader = TraceReader(FIXTURE)
        assert reader.verify()
        summary = reader.summary()
        assert summary["entries"] == 4
        assert summary["by_kind"] == {"checkpoint": 1, "event": 2, "receipt": 1}

    def test_resume_continues_the_chain(self, tmp_path):
        import shutil

        path = tmp_path / "trace.jsonl"
        shutil.copy(FIXTURE, path)
        with TraceRecorder(path) as rec:
            assert rec.count() == 4
            rec.record_decision("2026-03-01T09:20:00+00:00", {"c": 3})
        reader = TraceReader(path)
        assert reader.verify()
        assert reader.count() == 5
