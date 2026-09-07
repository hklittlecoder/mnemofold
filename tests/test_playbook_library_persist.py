"""Playbook library persistence: statuses, runs, and gating survive."""

from datetime import UTC, datetime

import pytest

from mnemofold.approvals import ApprovalQueue
from mnemofold.persist import PersistError, write_envelope
from mnemofold.playbooks import (
    Playbook,
    PlaybookLibrary,
    PlaybookRunner,
    PlaybookStatus,
    PlaybookStep,
)
from mnemofold.tools import ToolRegistry, ToolSpec

NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def make_library() -> PlaybookLibrary:
    library = PlaybookLibrary()
    pb = Playbook(
        playbook_id="pb-release",
        name="Release run",
        status=PlaybookStatus.ACTIVE,
        steps=[
            PlaybookStep(
                step_id="s1", title="Announce", tool="echo", inputs={"message": "announce"}
            )
        ],
        tags={"release"},
        confidence=0.75,
        run_count=2,
        metadata={"approved_by": "ana", "approved_at": "2026-03-02T09:00:00+00:00"},
    )
    library.add(pb)
    return library


class TestLibraryPersistence:
    def test_roundtrip_preserves_state(self, tmp_path):
        path = tmp_path / "library.json"
        library = make_library()
        library.save(path)
        loaded = PlaybookLibrary.load(path)
        assert loaded.to_dict() == library.to_dict()
        pb = loaded.get("pb-release")
        assert pb.status == PlaybookStatus.ACTIVE
        assert pb.run_count == 2

    def test_loaded_library_still_runs_gated(self, tmp_path):
        path = tmp_path / "library.json"
        make_library().save(path)
        loaded = PlaybookLibrary.load(path)
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="echo",
                description="echo",
                parameters={"message": {"type": "string"}},
                required=["message"],
            ),
            lambda message: {"echo": message},
        )
        runner = PlaybookRunner(library=loaded, queue=ApprovalQueue(), registry=registry)
        rid = runner.request_run("pb-release", requester="ana", approver="boss", now=NOW)
        runner.queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.status == "completed"
        assert loaded.get("pb-release").run_count == 3

    def test_load_rejects_foreign_schema(self, tmp_path):
        path = tmp_path / "other.json"
        write_envelope(path, "plan", {"plan_id": "p"})
        with pytest.raises(PersistError, match="schema mismatch"):
            PlaybookLibrary.load(path)

    def test_save_bytes_deterministic(self, tmp_path):
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        make_library().save(a)
        make_library().save(b)
        assert a.read_bytes() == b.read_bytes()

    def test_empty_library_roundtrip(self, tmp_path):
        path = tmp_path / "empty.json"
        PlaybookLibrary().save(path)
        assert PlaybookLibrary.load(path).total_count() == 0
