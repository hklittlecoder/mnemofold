import json
from pathlib import Path

from mnemofold.replay import (
    Replayer,
    TraceEntry,
    TraceEntryKind,
    TraceReader,
    TraceRecorder,
    trace_diff,
)


def _tmp_path(tmpdir, name):
    return Path(tmpdir) / name


def test_trace_entry_roundtrip():
    entry = TraceEntry(
        kind=TraceEntryKind.EVENT,
        timestamp="2026-03-15T10:00:00+00:00",
        entry_id="e1",
        payload={"type": "mail", "subject": "Hello"},
    )
    d = entry.to_dict()
    back = TraceEntry.from_dict(d)
    assert back.kind == entry.kind
    assert back.timestamp == entry.timestamp
    assert back.entry_id == entry.entry_id
    assert back.payload == entry.payload


def test_recorder_basic(tmp_path):
    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("2026-01-01T00:00:00Z", {"type": "mail", "id": "m1"})
        rec.record_decision("2026-01-01T00:01:00Z", {"decision": "approve"})
        assert rec.count() == 2
        h1 = rec.last_hash()
        rec.record_recall("2026-01-01T00:02:00Z", {"query": "test"})
        assert rec.count() == 3
        assert rec.last_hash() != h1


def test_reader_verifies_chain(tmp_path):
    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("t1", {"a": 1})
        rec.record_event("t2", {"b": 2})
    reader = TraceReader(p)
    assert reader.verify()
    assert reader.count() == 2


def test_reader_detects_tampering(tmp_path):
    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("t1", {"a": 1})
        rec.record_event("t2", {"b": 2})

    lines = p.read_text().splitlines()
    # Tamper with the second line's payload
    obj = json.loads(lines[1])
    obj["entry"]["payload"]["b"] = 999
    lines[1] = json.dumps(obj, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")

    reader = TraceReader(p)
    assert not reader.verify()


def test_reader_detects_truncation(tmp_path):
    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("t1", {"a": 1})
        rec.record_event("t2", {"b": 2})
        rec.record_event("t3", {"c": 3})

    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:2]) + "\n")

    reader = TraceReader(p)
    # Truncation still verifies (prefix is valid chain)
    assert reader.verify()
    assert reader.count() == 2


def test_replayer_calls_callbacks(tmp_path):
    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("t1", {"type": "mail"})
        rec.record_decision("t2", {"result": "ok"})
        rec.record_recall("t3", {"query": "q"})
        rec.record_receipt("t4", {"tool": "send"})

    events = []
    decisions = []
    recalls = []
    receipts = []

    replayer = Replayer(p)
    count = replayer.replay(
        on_event=lambda p: events.append(p),
        on_decision=lambda p: decisions.append(p),
        on_recall=lambda p: recalls.append(p),
        on_receipt=lambda p: receipts.append(p),
    )
    assert count == 4
    assert len(events) == 1
    assert events[0]["type"] == "mail"
    assert len(decisions) == 1
    assert decisions[0]["result"] == "ok"
    assert len(recalls) == 1
    assert len(receipts) == 1


def test_checkpoint_and_resume(tmp_path):
    p = tmp_path / "trace.jsonl"
    with TraceRecorder(p) as rec:
        rec.record_event("t1", {"a": 1})
        rec.checkpoint("t1.5", {"step": 1, "score": 0.5})
        rec.record_event("t2", {"b": 2})

    replayer = Replayer(p)
    ckpt = replayer.last_checkpoint()
    assert ckpt is not None
    assert ckpt["step"] == 1
    assert ckpt["score"] == 0.5


def test_trace_diff_identical(tmp_path):
    p1 = tmp_path / "a.jsonl"
    p2 = tmp_path / "b.jsonl"
    for p in (p1, p2):
        with TraceRecorder(p) as rec:
            rec.record_event("t1", {"x": 1})
            rec.record_event("t2", {"x": 2})
    diff = trace_diff(p1, p2)
    assert diff["equal"] is True
    assert diff["matching"] == 2
    assert diff["first_mismatch"] is None


def test_trace_diff_mismatch(tmp_path):
    p1 = tmp_path / "a.jsonl"
    p2 = tmp_path / "b.jsonl"
    with TraceRecorder(p1) as rec:
        rec.record_event("t1", {"x": 1})
        rec.record_event("t2", {"x": 2})
    with TraceRecorder(p2) as rec:
        rec.record_event("t1", {"x": 1})
        rec.record_event("t2", {"x": 99})
    diff = trace_diff(p1, p2)
    assert diff["equal"] is False
    assert diff["first_mismatch"] == 1
    assert diff["matching"] == 1


def test_trace_diff_length_mismatch(tmp_path):
    p1 = tmp_path / "a.jsonl"
    p2 = tmp_path / "b.jsonl"
    with TraceRecorder(p1) as rec:
        rec.record_event("t1", {"x": 1})
    with TraceRecorder(p2) as rec:
        rec.record_event("t1", {"x": 1})
        rec.record_event("t2", {"x": 2})
    diff = trace_diff(p1, p2)
    assert diff["equal"] is False
    assert diff["a_count"] == 1
    assert diff["b_count"] == 2


def test_deterministic_trace(tmp_path):
    """Same content in same order produces same final hash."""
    p1 = tmp_path / "t1.jsonl"
    p2 = tmp_path / "t2.jsonl"
    for p in (p1, p2):
        with TraceRecorder(p) as rec:
            rec.record_event("2026-01-01T00:00:00Z", {"type": "mail", "id": "1"})
            rec.record_decision("2026-01-01T00:01:00Z", {"status": "approved"})
    r1 = TraceReader(p1)
    r2 = TraceReader(p2)
    assert r1.verify() and r2.verify()
    # Read last hash from both
    last1 = None
    last2 = None
    with p1.open() as f:
        for line in f:
            last1 = json.loads(line)["hash"]
    with p2.open() as f:
        for line in f:
            last2 = json.loads(line)["hash"]
    assert last1 == last2


def test_empty_trace(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    reader = TraceReader(p)
    assert reader.count() == 0
    assert reader.verify()
    assert reader.entries() == []


class TestReplayResume:
    def test_resume_continues_chain(self, tmp_path):
        path = tmp_path / "trace.jsonl"
        with TraceRecorder(path) as rec:
            rec.record_event("t0", {"a": 1})
            rec.record_decision("t1", {"b": 2})
        # simulate a process restart: a fresh recorder on the same file
        with TraceRecorder(path) as resumed:
            assert resumed.count() == 2
            resumed.record_event("t2", {"c": 3})
        reader = TraceReader(path)
        assert reader.verify()  # one unbroken chain across the restart
        assert reader.count() == 3

    def test_resume_on_fresh_file_starts_at_genesis(self, tmp_path):
        path = tmp_path / "new.jsonl"
        rec = TraceRecorder(path)
        assert rec.count() == 0
        assert rec.last_hash() == "0" * 64
        rec.close()

    def test_replay_from_last_checkpoint_skips_prefix(self, tmp_path):
        path = tmp_path / "trace.jsonl"
        with TraceRecorder(path) as rec:
            rec.record_event("t0", {"step": 0})
            rec.checkpoint("t1", {"at": 1})
            rec.record_event("t2", {"step": 2})
            rec.record_event("t3", {"step": 3})
        seen: list[dict] = []
        count = Replayer(path).replay_from_last_checkpoint(
            on_event=lambda payload: seen.append(payload)
        )
        assert count == 2
        assert seen == [{"step": 2}, {"step": 3}]

    def test_replay_from_checkpoint_without_checkpoint_replays_all(self, tmp_path):
        path = tmp_path / "trace.jsonl"
        with TraceRecorder(path) as rec:
            rec.record_event("t0", {"step": 0})
            rec.record_event("t1", {"step": 1})
        seen: list[dict] = []
        count = Replayer(path).replay_from_last_checkpoint(
            on_event=lambda payload: seen.append(payload)
        )
        assert count == 2
        assert len(seen) == 2

    def test_resumed_recorder_hashes_match_single_session(self, tmp_path):
        # Writing 2+1 across a restart yields the same chain as 3 at once.
        split = tmp_path / "split.jsonl"
        with TraceRecorder(split) as rec:
            rec.record_event("t0", {"a": 1})
            rec.record_event("t1", {"a": 2})
        with TraceRecorder(split) as rec:
            rec.record_event("t2", {"a": 3})

        single = tmp_path / "single.jsonl"
        with TraceRecorder(single) as rec:
            rec.record_event("t0", {"a": 1})
            rec.record_event("t1", {"a": 2})
            rec.record_event("t2", {"a": 3})

        assert TraceReader(split).head() == TraceReader(single).head()
