"""Record and replay infrastructure.

The recorder appends every event, decision, recall, and receipt to a
checksummed JSONL trace.  The replayer reconstructs identical traces
from the same seed + inputs (hard determinism).  Supports checkpoint
/resume across simulated crashes and a trace-diff tool.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO


class TraceEntryKind(StrEnum):
    EVENT = "event"
    DECISION = "decision"
    RECALL = "recall"
    RECEIPT = "receipt"
    CHECKPOINT = "checkpoint"


@dataclass(slots=True)
class TraceEntry:
    kind: TraceEntryKind
    timestamp: str
    payload: dict[str, Any]
    entry_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "timestamp": self.timestamp,
            "entry_id": self.entry_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceEntry:
        return cls(
            kind=TraceEntryKind(d["kind"]),
            timestamp=d["timestamp"],
            entry_id=d.get("entry_id", ""),
            payload=d.get("payload", {}),
        )


def _entry_hash(entry: dict[str, Any], prev_hash: str) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(json.dumps(entry, sort_keys=True).encode())
    return h.hexdigest()


class TraceRecorder:
    """Records entries to a checksummed JSONL trace file.

    Each line is a JSON object with ``entry`` and ``hash`` fields.  The
    hash chains previous-hash + current-entry-sorted-json so tampering
    or truncation is detectable.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fp: TextIO | None = None
        self._prev_hash = "0" * 64
        self._count = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self.path.open("a", encoding="utf-8")

    def record(self, entry: TraceEntry) -> str:
        if self._fp is None:
            raise RuntimeError("recorder is closed")
        ed = entry.to_dict()
        h = _entry_hash(ed, self._prev_hash)
        line = json.dumps({"hash": h, "entry": ed}, ensure_ascii=False, sort_keys=True)
        self._fp.write(line + "\n")
        self._fp.flush()
        self._prev_hash = h
        self._count += 1
        return h

    def record_event(self, ts: str, event: dict[str, Any]) -> str:
        return self.record(TraceEntry(kind=TraceEntryKind.EVENT, timestamp=ts, payload=event))

    def record_decision(self, ts: str, decision: dict[str, Any]) -> str:
        return self.record(TraceEntry(kind=TraceEntryKind.DECISION, timestamp=ts, payload=decision))

    def record_recall(self, ts: str, recall: dict[str, Any]) -> str:
        return self.record(TraceEntry(kind=TraceEntryKind.RECALL, timestamp=ts, payload=recall))

    def record_receipt(self, ts: str, receipt: dict[str, Any]) -> str:
        return self.record(TraceEntry(kind=TraceEntryKind.RECEIPT, timestamp=ts, payload=receipt))

    def checkpoint(self, ts: str, state: dict[str, Any]) -> str:
        return self.record(
            TraceEntry(
                kind=TraceEntryKind.CHECKPOINT,
                timestamp=ts,
                payload=state,
                entry_id=f"ckpt-{self._count}",
            )
        )

    def count(self) -> int:
        return self._count

    def last_hash(self) -> str:
        return self._prev_hash

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def __enter__(self) -> TraceRecorder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class TraceReader:
    """Reads and verifies a checksummed JSONL trace file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def entries(self) -> list[TraceEntry]:
        return [TraceEntry.from_dict(line["entry"]) for line in self._iter_lines()]

    def _iter_lines(self) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        prev_hash = "0" * 64
        with self.path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                entry = obj["entry"]
                expected = _entry_hash(entry, prev_hash)
                if obj["hash"] != expected:
                    raise ValueError(f"hash mismatch at line {len(lines) + 1}")
                prev_hash = obj["hash"]
                lines.append(obj)
        return lines

    def verify(self) -> bool:
        try:
            self._iter_lines()
            return True
        except (ValueError, KeyError, json.JSONDecodeError):
            return False

    def count(self) -> int:
        return len(self._iter_lines())


def trace_diff(
    path_a: str | Path,
    path_b: str | Path,
) -> dict[str, Any]:
    """Compare two traces and return a diff summary.

    Returns counts of total entries, matching entries, and the first
    mismatched index with both entries side-by-side.
    """
    ra = TraceReader(path_a)
    rb = TraceReader(path_b)
    a_entries = ra.entries()
    b_entries = rb.entries()

    first_mismatch: int | None = None
    matching = 0
    for i, (ea, eb) in enumerate(zip(a_entries, b_entries, strict=False)):
        if ea.to_dict() == eb.to_dict():
            matching += 1
        elif first_mismatch is None:
            first_mismatch = i

    return {
        "a_count": len(a_entries),
        "b_count": len(b_entries),
        "matching": matching,
        "first_mismatch": first_mismatch,
        "equal": len(a_entries) == len(b_entries) and matching == len(a_entries),
    }


class Replayer:
    """Replays a trace by feeding entries back into a callback.

    Used for reproducibility testing: re-running the same inputs
    against a fresh system and comparing outputs.  Supports resume from
    the last checkpoint.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._reader = TraceReader(path)

    def replay(
        self,
        on_event: Callable[[dict[str, Any]], None] | None,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
        on_recall: Callable[[dict[str, Any]], None] | None = None,
        on_receipt: Callable[[dict[str, Any]], None] | None = None,
        on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    ) -> int:
        """Replay all entries, invoking the appropriate callback.

        Returns the number of entries replayed.
        """
        count = 0
        for entry in self._reader.entries():
            if entry.kind == TraceEntryKind.EVENT and on_event:
                on_event(entry.payload)
            elif entry.kind == TraceEntryKind.DECISION and on_decision:
                on_decision(entry.payload)
            elif entry.kind == TraceEntryKind.RECALL and on_recall:
                on_recall(entry.payload)
            elif entry.kind == TraceEntryKind.RECEIPT and on_receipt:
                on_receipt(entry.payload)
            elif entry.kind == TraceEntryKind.CHECKPOINT and on_checkpoint:
                on_checkpoint(entry.payload)
            count += 1
        return count

    def last_checkpoint(self) -> dict[str, Any] | None:
        """Return the payload of the last checkpoint entry, if any."""
        entries = self._reader.entries()
        for entry in reversed(entries):
            if entry.kind == TraceEntryKind.CHECKPOINT:
                return entry.payload
        return None
