"""Approval-gated playbook execution."""

from datetime import UTC, datetime, timedelta

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


def raise_boom() -> None:
    raise RuntimeError("kaboom")


class TestPlaybookRunnerEdges:
    def test_denied_request_blocks_run(self):
        runner = make_runner()
        pb = make_playbook()
        runner.library.add(pb)
        rid = runner.request_run("pb_release", requester="a", approver="b", now=NOW)
        runner.queue.decide(rid, False, NOW, note="not this week")
        report = runner.execute(rid)
        assert report.status == "not_approved"
        assert "denied" in report.error
        assert pb.run_count == 0

    def test_expired_request_blocks_run(self):
        runner = make_runner()
        pb = make_playbook()
        runner.library.add(pb)
        rid = runner.request_run(
            "pb_release",
            requester="a",
            approver="b",
            now=NOW,
            expires_after=timedelta(hours=1),
        )
        expired = runner.queue.tick_expirations(NOW + timedelta(hours=2))
        assert [r.request_id for r in expired] == [rid]
        report = runner.execute(rid)
        assert report.status == "not_approved"
        assert "expired" in report.error
        assert pb.run_count == 0

    def test_failing_tool_stops_the_run(self):
        library = PlaybookLibrary()
        pb = Playbook(
            playbook_id="pb_x",
            name="X",
            status=PlaybookStatus.ACTIVE,
            steps=[
                PlaybookStep(step_id="s1", title="ok", tool="echo", inputs={"text": "hi"}),
                PlaybookStep(step_id="s2", title="boom", tool="boom"),
                PlaybookStep(step_id="s3", title="never", tool="echo", inputs={"text": "no"}),
            ],
        )
        library.add(pb)
        registry = make_registry()
        registry.register(ToolSpec(name="boom", description="always raises"), raise_boom)
        queue = ApprovalQueue()
        runner = PlaybookRunner(library=library, queue=queue, registry=registry)
        rid = runner.request_run("pb_x", requester="a", approver="b", now=NOW)
        queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.status == "failed"
        assert [r.step_id for r in report.step_results] == ["s1", "s2"]
        assert "kaboom" in report.step_results[1].error
        assert pb.run_count == 0

    def test_precondition_order_overrides_declaration(self):
        library = PlaybookLibrary()
        pb = Playbook(
            playbook_id="pb_order",
            name="Order",
            status=PlaybookStatus.ACTIVE,
            steps=[
                PlaybookStep(
                    step_id="s2",
                    title="second",
                    tool="echo",
                    inputs={"text": "2"},
                    preconditions=["s1"],
                ),
                PlaybookStep(step_id="s1", title="first", tool="echo", inputs={"text": "1"}),
            ],
        )
        library.add(pb)
        queue = ApprovalQueue()
        runner = PlaybookRunner(library=library, queue=queue, registry=make_registry())
        rid = runner.request_run("pb_order", requester="a", approver="b", now=NOW)
        queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.succeeded
        assert [r.step_id for r in report.step_results] == ["s1", "s2"]

    def test_unknown_tool_fails_the_run(self):
        library = PlaybookLibrary()
        pb = Playbook(
            playbook_id="pb_ghost",
            name="Ghost",
            status=PlaybookStatus.ACTIVE,
            steps=[PlaybookStep(step_id="s1", title="ghost", tool="ghost")],
        )
        library.add(pb)
        queue = ApprovalQueue()
        runner = PlaybookRunner(library=library, queue=queue, registry=make_registry())
        rid = runner.request_run("pb_ghost", requester="a", approver="b", now=NOW)
        queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.status == "failed"
        assert "unknown tool" in report.step_results[0].error
        assert pb.run_count == 0

    def test_structurally_invalid_playbook_is_blocked(self):
        library = PlaybookLibrary()
        pb = Playbook(
            playbook_id="pb_bad",
            name="Bad",
            status=PlaybookStatus.ACTIVE,
            steps=[
                PlaybookStep(step_id="s1", title="a", tool="echo", inputs={"text": "1"}),
                PlaybookStep(step_id="s1", title="dup", tool="echo", inputs={"text": "2"}),
            ],
        )
        library.add(pb)
        queue = ApprovalQueue()
        runner = PlaybookRunner(library=library, queue=queue, registry=make_registry())
        rid = runner.request_run("pb_bad", requester="a", approver="b", now=NOW)
        queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.status == "blocked"
        assert "duplicate" in report.error
        assert pb.run_count == 0

    def test_steps_without_tools_are_skipped_marked(self):
        library = PlaybookLibrary()
        pb = Playbook(
            playbook_id="pb_manual",
            name="Manual",
            status=PlaybookStatus.ACTIVE,
            steps=[
                PlaybookStep(step_id="m1", title="think", tool=""),
                PlaybookStep(step_id="m2", title="say", tool="echo", inputs={"text": "x"}),
            ],
        )
        library.add(pb)
        queue = ApprovalQueue()
        runner = PlaybookRunner(library=library, queue=queue, registry=make_registry())
        rid = runner.request_run("pb_manual", requester="a", approver="b", now=NOW)
        queue.decide(rid, True, NOW)
        report = runner.execute(rid)
        assert report.succeeded
        assert report.step_results[0].skipped
        assert not report.step_results[1].skipped
        assert pb.run_count == 1
