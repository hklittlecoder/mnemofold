"""Integrity verification must fail loudly on real corruption.

Two failure modes are simulated: a forgotten memory smuggled back into
the store behind the recall guard, and a payload edit inside the
hash-chained trace file. The trace case also documents the fail-fast
resume contract — a workspace with a broken chain refuses to reopen.
"""

import json

import pytest

from mnemofold.memory import MemoryItem, MemoryTier
from mnemofold.replay import TraceReader
from mnemofold.workspace import Workspace

from .test_workspace_integrity import NOW, first_item, make_workspace


class TestIntegrityNegatives:
    def test_resurrected_item_is_detected(self, tmp_path):
        ws = make_workspace(tmp_path)
        target = first_item(ws).item_id
        ws.forget(target, now=NOW, reason="test")
        assert ws.recall(target) is None  # the guard still works

        # smuggle the content back behind the guard's back
        ws.store.add(MemoryItem(item_id=target, tier=MemoryTier.EPISODIC, content="resurrected"))
        report = ws.verify_integrity()
        assert report["ok"] is False
        assert report["checks"]["no_resurrection"] is False
        assert report["resurrected_keys"] == [target]
        ws.close()

    def test_trace_tampering_blocks_reopen_and_fails_verify(self, tmp_path):
        ws = make_workspace(tmp_path)
        trace_path = ws.trace.path
        ws_dir = ws.path
        ws.close()

        lines = trace_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2
        record = json.loads(lines[0])
        record["entry"]["payload"]["tampered"] = True
        lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
        trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # fail-fast resume: a broken chain refuses to reopen the workspace
        with pytest.raises(ValueError, match="hash mismatch"):
            Workspace(ws_dir)

        # the standalone reader reports the same fact as verify()=False,
        # which is exactly what verify_integrity's trace_chain check uses
        assert TraceReader(trace_path).verify() is False

    def test_clean_reopen_passes(self, tmp_path):
        ws = make_workspace(tmp_path)
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)
        report = reopened.verify_integrity()
        assert report["ok"] is True
        reopened.close()
