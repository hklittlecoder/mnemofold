"""Golden bytes for DeletionReport JSON and Markdown exports."""

from datetime import UTC, datetime
from pathlib import Path

from mnemofold.deletion import DeletionAuditEntry, DeletionReason, DeletionReport

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "deletion_report_golden.json"
FIXTURE_MD = Path(__file__).parent / "fixtures" / "deletion_report_golden.md"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def make_report() -> DeletionReport:
    return DeletionReport(
        requested_key="evt_abc",
        reason=DeletionReason.USER_REQUEST,
        requested_at=NOW,
        deleted=[
            DeletionAuditEntry(
                key="evt_abc",
                kind="memory",
                reason=DeletionReason.USER_REQUEST,
                deleted_at=NOW,
                cascade_depth=0,
            ),
            DeletionAuditEntry(
                key="edge-1",
                kind="edge",
                reason=DeletionReason.USER_REQUEST,
                deleted_at=NOW,
                cascade_depth=1,
            ),
        ],
        blocked=["held-1"],
        errors=["target not found: ghost"],
    )


class TestDeletionGoldens:
    def test_json_matches_golden(self):
        assert make_report().to_json() == FIXTURE_JSON.read_text(encoding="utf-8")

    def test_markdown_matches_golden(self):
        assert make_report().to_markdown() == FIXTURE_MD.read_text(encoding="utf-8")

    def test_regeneration_is_stable(self):
        assert make_report().to_json() == make_report().to_json()
        assert make_report().to_markdown() == make_report().to_markdown()
