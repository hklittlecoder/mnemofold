"""Tests for playbooks."""

from __future__ import annotations

import pytest

from mnemofold.playbooks import (
    Playbook,
    PlaybookLibrary,
    PlaybookStatus,
    PlaybookStep,
)


class TestPlaybook:
    def test_create(self):
        pb = Playbook("pb1", "Onboarding")
        assert pb.status == PlaybookStatus.PROPOSED
        assert pb.version == 1

    def test_can_run(self):
        assert Playbook("p", "n", status=PlaybookStatus.APPROVED).can_run()
        assert not Playbook("p", "n", status=PlaybookStatus.PROPOSED).can_run()


class TestPlaybookLibrary:
    def test_add_get(self):
        lib = PlaybookLibrary()
        lib.add(Playbook("pb1", "Test"))
        assert lib.get("pb1") is not None

    def test_approve(self):
        lib = PlaybookLibrary()
        lib.add(Playbook("pb1", "Test"))
        assert lib.approve("pb1", "alice", "2024-01-01T00:00:00+00:00")
        assert lib.get("pb1").status == PlaybookStatus.APPROVED

    def test_deprecate(self):
        lib = PlaybookLibrary()
        lib.add(Playbook("pb1", "Test", status=PlaybookStatus.ACTIVE))
        assert lib.deprecate("pb1", "obsolete")

    def test_suggest(self):
        lib = PlaybookLibrary()
        lib.add(Playbook("p1", "Onboard", tags={"onboarding", "hr"}, confidence=0.8))
        lib.add(Playbook("p2", "Deploy", tags={"deploy", "eng"}, confidence=0.9))
        suggestions = lib.suggest({"onboarding", "eng"})
        ids = {s.playbook_id for s in suggestions}
        assert "p1" in ids and "p2" in ids

    def test_create_revision(self):
        lib = PlaybookLibrary()
        lib.add(Playbook("pb1", "Test", steps=[PlaybookStep("s1", "Step 1")], version=1))
        new = lib.create_revision("pb1", [PlaybookStep("s1", "1"), PlaybookStep("s2", "2")])
        assert new.version == 2
        assert new.status == PlaybookStatus.DRAFT
        assert new.total_steps() == 2


class TestPlaybookLifecycle:
    def _library(self) -> PlaybookLibrary:
        library = PlaybookLibrary()
        library.add(
            Playbook(
                playbook_id="pb1",
                name="Release checklist",
                tags={"release"},
                confidence=0.8,
                steps=[PlaybookStep(step_id="s1", title="Run tests", tool="echo")],
            )
        )
        return library

    def test_full_happy_path(self):
        library = self._library()
        pb = library.get("pb1")
        assert pb is not None
        assert pb.status == PlaybookStatus.PROPOSED
        assert not pb.can_run()
        assert library.approve("pb1", "alice", "2025-03-01T00:00:00+00:00")
        assert library.activate("pb1")
        pb = library.get("pb1")
        assert pb is not None
        assert pb.status == PlaybookStatus.ACTIVE
        assert pb.can_run()
        assert library.record_run("pb1")
        assert library.get("pb1").run_count == 1

    def test_activate_requires_approval(self):
        library = self._library()
        assert library.activate("pb1") is False
        assert library.get("pb1").status == PlaybookStatus.PROPOSED

    def test_activate_unknown_playbook(self):
        assert self._library().activate("nope") is False

    def test_revoke_is_one_way(self):
        library = self._library()
        library.approve("pb1", "alice", "2025-03-01T00:00:00+00:00")
        library.activate("pb1")
        assert library.revoke("pb1", "obsolete tooling")
        pb = library.get("pb1")
        assert pb is not None
        assert pb.status == PlaybookStatus.REVOKED
        assert pb.metadata["revocation_reason"] == "obsolete tooling"
        assert library.revoke("pb1", "again") is False
        assert not pb.can_run()
        assert library.record_run("pb1") is False

    def test_record_run_rejects_unrunnable(self):
        library = self._library()
        assert library.record_run("pb1") is False  # still proposed
        library.deprecate("pb1", "old")
        assert library.record_run("pb1") is False

    def test_revoked_and_deprecated_never_suggested(self):
        library = PlaybookLibrary()
        library.add(
            Playbook(
                "rev", "Revoked", status=PlaybookStatus.PROPOSED, tags={"release"}, confidence=0.9
            )
        )
        library.add(
            Playbook(
                "dep",
                "Deprecated",
                status=PlaybookStatus.PROPOSED,
                tags={"release"},
                confidence=0.9,
            )
        )
        library.add(
            Playbook(
                "ok", "Healthy", status=PlaybookStatus.APPROVED, tags={"release"}, confidence=0.5
            )
        )
        library.revoke("rev", "unsafe")
        library.deprecate("dep", "stale")
        suggested = library.suggest({"release"})
        assert [pb.playbook_id for pb in suggested] == ["ok"]


class TestPlaybookSerialization:
    def _playbook(self) -> Playbook:
        return Playbook(
            playbook_id="pb1",
            name="Release checklist",
            description="Ship it safely",
            status=PlaybookStatus.APPROVED,
            tags={"release", "ops"},
            confidence=0.75,
            run_count=2,
            steps=[
                PlaybookStep(
                    step_id="s1",
                    title="Run tests",
                    tool="echo",
                    inputs={"message": "test"},
                    preconditions=["ci_green"],
                ),
                PlaybookStep(step_id="s2", title="Tag release", tool="noop"),
            ],
            metadata={"approved_by": "alice"},
        )

    def test_roundtrip_equality(self):
        pb = self._playbook()
        assert Playbook.from_dict(pb.to_dict()) == pb

    def test_roundtrip_preserves_steps(self):
        pb = self._playbook()
        restored = Playbook.from_dict(pb.to_dict())
        assert restored.steps == pb.steps
        assert restored.steps[0].preconditions == ["ci_green"]

    def test_digest_stable_and_sensitive(self):
        pb = self._playbook()
        assert pb.digest() == self._playbook().digest()
        pb.run_count += 1
        assert pb.digest() != self._playbook().digest()

    def test_revision_lineage_accumulates(self):
        library = PlaybookLibrary()
        library.add(self._playbook())
        v2 = library.create_revision("pb1", [PlaybookStep(step_id="s1", title="Only step")])
        assert v2 is not None
        assert v2.version == 2
        assert v2.derived_from == ["pb1"]
        v3 = library.create_revision(v2.playbook_id, [PlaybookStep(step_id="s1", title="Again")])
        assert v3 is not None
        assert v3.previous_versions == ["pb1", v2.playbook_id]
        assert v3.confidence == pytest.approx(0.75 * 0.9 * 0.9)

    def test_revision_starts_as_draft_and_not_runnable(self):
        library = PlaybookLibrary()
        library.add(self._playbook())
        v2 = library.create_revision("pb1", [])
        assert v2 is not None
        assert v2.status == PlaybookStatus.DRAFT
        assert not v2.can_run()

    def test_revision_digest_differs_from_original(self):
        library = PlaybookLibrary()
        original = self._playbook()
        library.add(original)
        v2 = library.create_revision("pb1", [PlaybookStep(step_id="s1", title="Only step")])
        assert v2 is not None
        assert v2.digest() != original.digest()
