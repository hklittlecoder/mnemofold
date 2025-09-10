"""Assistant-layer property tests: batching conservation, replay identity.

Triage batching re-routes scored items between buckets but must never
drop one, and a recorded trace must replay byte-identically from the
same script — both are invariants of the machinery, verified over
seeded random inputs and scripted traces.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from mnemofold.replay import Replayer, TraceReader, TraceRecorder
from mnemofold.triage import TriageBatcher, TriagePriority, TriageResult

PRIORITIES = list(TriagePriority)


def _random_results(rng: random.Random, n: int) -> list[TriageResult]:
    return [
        TriageResult(
            item_id=f"t{i:03d}",
            score=round(rng.uniform(0.0, 1.0), 3),
            priority=rng.choice(PRIORITIES),
        )
        for i in range(n)
    ]


def _script(recorder: TraceRecorder) -> None:
    recorder.record_event("2025-01-01T09:00:00+00:00", {"event_id": "e1", "type": "mail_received"})
    recorder.record_decision("2025-01-01T10:00:00+00:00", {"decision": "ship friday"})
    recorder.record_recall("2025-01-01T11:00:00+00:00", {"query": "ship", "hits": ["e1"]})
    recorder.checkpoint("2025-01-01T12:00:00+00:00", {"memories": 3})
    recorder.record_receipt("2025-01-01T13:00:00+00:00", {"action": "ingest", "added": 2})


class TestBatchingConservation:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_batching_reroutes_but_never_drops(self, seed):
        rng = random.Random(seed)
        results = _random_results(rng, 30)
        plan = TriageBatcher(max_act_now=3, max_review=5).batch(results)
        assert plan.total() == len(results)
        ids = [r.item_id for r in (*plan.act_now, *plan.review, *plan.defer)]
        assert sorted(ids) == sorted(r.item_id for r in results)
        assert len(ids) == len(set(ids))
        assert len(plan.act_now) <= 3
        assert len(plan.review) <= 5

    def test_urgent_overflow_is_marked(self):
        results = [TriageResult(f"u{i}", 0.9, TriagePriority.URGENT) for i in range(5)]
        plan = TriageBatcher(max_act_now=2, max_review=2).batch(results)
        assert len(plan.act_now) == 2
        overflow = [r for r in (*plan.review, *plan.defer) if "batch_overflow" in r.reasons]
        assert len(overflow) == 3

    def test_low_priority_defers_without_overflow_mark(self):
        results = [TriageResult(f"l{i}", 0.1, TriagePriority.LOW) for i in range(4)]
        plan = TriageBatcher().batch(results)
        assert len(plan.defer) == 4
        assert all(not r.reasons for r in plan.defer)


class TestReplayByteIdentity:
    def test_identical_scripts_produce_identical_bytes(self, tmp_path: Path):
        first = tmp_path / "a.jsonl"
        second = tmp_path / "b.jsonl"
        for path in (first, second):
            with TraceRecorder(path) as recorder:
                _script(recorder)
        assert first.read_bytes() == second.read_bytes()

    def test_replay_reconstructs_recorded_payloads(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        with TraceRecorder(path) as recorder:
            _script(recorder)
        events: list[dict] = []
        receipts: list[dict] = []
        count = Replayer(path).replay(events.append, on_receipt=receipts.append)
        assert count == 5
        assert count == TraceReader(path).count()
        assert events == [{"event_id": "e1", "type": "mail_received"}]
        assert receipts == [{"action": "ingest", "added": 2}]
        assert TraceReader(path).verify()

    def test_resume_replays_only_the_tail_after_checkpoint(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        with TraceRecorder(path) as recorder:
            _script(recorder)
        events: list[dict] = []
        replayed = Replayer(path).replay_from_last_checkpoint(events.append)
        assert replayed == 1
        assert events == []

    def test_tampered_trace_fails_verification(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        with TraceRecorder(path) as recorder:
            _script(recorder)
        lines = path.read_text().splitlines()
        record = json.loads(lines[1])
        record["entry"]["payload"]["decision"] = "ship monday"
        lines[1] = json.dumps(record, sort_keys=True)
        path.write_text("\n".join(lines) + "\n")
        assert not TraceReader(path).verify()
