"""Tests for playbooks."""

from __future__ import annotations

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
