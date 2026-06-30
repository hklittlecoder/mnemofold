"""Deletion audit exports: full detail, stable bytes, honest sections."""

import json
from datetime import UTC, datetime

from mnemofold.deletion import (
    DeletionAuditEntry,
    DeletionReason,
    DeletionReport,
)

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


class TestDeletionExports:
    def test_to_dict_carries_every_entry(self):
        d = make_report().to_dict()
        assert d["total_deleted"] == 2
        assert [e["key"] for e in d["deleted"]] == ["evt_abc", "edge-1"]
        assert d["deleted"][1]["cascade_depth"] == 1
        assert d["blocked"] == ["held-1"]
        assert d["errors"] == ["target not found: ghost"]

    def test_json_is_sorted_and_parseable(self):
        text = make_report().to_json()
        assert json.loads(text) == make_report().to_dict()
        assert text == make_report().to_json()

    def test_markdown_sections(self):
        md = make_report().to_markdown()
        assert md.startswith("# Deletion Report")
        assert "| evt_abc | memory | 0 |" in md
        assert "## Blocked (protected)" in md
        assert "- `held-1`" in md
        assert "- target not found: ghost" in md

    def test_empty_report_omits_sections(self):
        report = DeletionReport(
            requested_key="ghost", reason=DeletionReason.ERROR_CORRECTION, requested_at=NOW
        )
        md = report.to_markdown()
        assert "## Deleted" not in md
        assert "## Blocked" not in md
        assert "- deleted: 0" in md

    def test_summary_and_detail_agree(self):
        report = make_report()
        assert report.summary_dict()["total_deleted"] == report.to_dict()["total_deleted"]
        assert report.summary_dict()["deleted_by_kind"] == {"edge": 1, "memory": 1}
