"""Golden bytes for the persisted playbook library."""

from pathlib import Path

from mnemofold.playbooks import (
    Playbook,
    PlaybookLibrary,
    PlaybookStatus,
    PlaybookStep,
)

FIXTURE = Path(__file__).parent / "fixtures" / "playbook_library_golden.json"


def make_library() -> PlaybookLibrary:
    library = PlaybookLibrary()
    library.add(
        Playbook(
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
    )
    return library


class TestLibraryGolden:
    def test_save_matches_golden_bytes(self, tmp_path):
        path = tmp_path / "library.json"
        make_library().save(path)
        assert path.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    def test_golden_loads_to_equal_library(self):
        assert PlaybookLibrary.load(FIXTURE).to_dict() == make_library().to_dict()

    def test_regeneration_is_stable(self, tmp_path):
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        make_library().save(a)
        make_library().save(b)
        assert a.read_bytes() == b.read_bytes() == FIXTURE.read_bytes()
