"""Approval-gated playbook execution."""

from datetime import UTC, datetime

from mnemofold.approvals import ApprovalQueue
from mnemofold.playbooks import (
    Playbook,
    PlaybookLibrary,
    PlaybookRunner,
    PlaybookStatus,
    PlaybookStep,
)
from mnemofold.tools import ToolRegistry, ToolSpec

NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="echo text back",
            parameters={"text": {"type": "string"}},
            required=["text"],
        ),
        lambda text: {"echo": text},
    )
    return registry


def make_playbook(status: PlaybookStatus = PlaybookStatus.ACTIVE) -> Playbook:
    return Playbook(
        playbook_id="pb_release",
        name="Release run",
        status=status,
        steps=[
            PlaybookStep(step_id="s1", title="Announce", tool="echo", inputs={"text": "hi"}),
        ],
    )


def make_runner() -> PlaybookRunner:
    return PlaybookRunner(
        library=PlaybookLibrary(), queue=ApprovalQueue(), registry=make_registry()
    )


class TestPlaybookRunner:
    def test_approved_run_completes_and_counts(self):
        runner = make_runner()
        pb = make_playbook()
        runner.library.add(pb)
        rid = runner.request_run("pb_release", requester="ana", approver="boss", now=NOW)
        assert rid is not None
        runner.queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.succeeded
        assert report.status == "completed"
        assert pb.run_count == 1
        assert report.step_results[0].output == {"echo": "hi"}
        assert report.to_dict()["status"] == "completed"

    def test_request_creates_pending_approval(self):
        runner = make_runner()
        runner.library.add(make_playbook())
        rid = runner.request_run("pb_release", requester="ana", approver="boss", now=NOW)
        pending = runner.queue.pending()
        assert [r.request_id for r in pending] == [rid]
        assert pending[0].item_kind == "playbook_run"
        assert "Release run" in pending[0].summary

    def test_proposed_playbook_cannot_be_requested(self):
        runner = make_runner()
        runner.library.add(make_playbook(status=PlaybookStatus.PROPOSED))
        assert runner.request_run("pb_release", requester="a", approver="b", now=NOW) is None
        assert runner.queue.requests == []

    def test_unknown_playbook_cannot_be_requested(self):
        runner = make_runner()
        assert runner.request_run("nope", requester="a", approver="b", now=NOW) is None

    def test_execute_unknown_request(self):
        runner = make_runner()
        report = runner.execute("missing")
        assert report.status == "unknown_request"
        assert report.playbook_id == ""

    def test_pending_request_is_not_executed(self):
        runner = make_runner()
        pb = make_playbook()
        runner.library.add(pb)
        rid = runner.request_run("pb_release", requester="a", approver="b", now=NOW)
        report = runner.execute(rid)
        assert report.status == "not_approved"
        assert pb.run_count == 0
