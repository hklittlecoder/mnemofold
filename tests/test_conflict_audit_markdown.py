"""Markdown rendering of contradiction audit reports."""

from mnemofold.conflict import (
    ConflictResolver,
    EvidenceSource,
    FactEvidence,
    audit_report_markdown,
)


def make_contradictions():
    resolver = ConflictResolver()
    ea = FactEvidence(
        source=EvidenceSource.UNVERIFIED,
        timestamp="2026-03-01T00:00:00+00:00",
        source_id="s1",
    )
    eb = FactEvidence(
        source=EvidenceSource.VERIFIED,
        timestamp="2026-03-02T00:00:00+00:00",
        source_id="s2",
    )
    return resolver.resolve_many([("owner", "ana", ea, "bo", eb)])


class TestAuditMarkdown:
    def test_empty_report(self):
        md = audit_report_markdown(
            {"total": 0, "resolved": 0, "unresolved": 0, "by_reason": {}, "contradictions": []}
        )
        assert "# Contradiction Audit" in md
        assert "- total: 0" in md
        assert "- (none)" in md
        assert "_No contradictions recorded._" in md

    def test_real_audit_renders(self):
        contradictions = make_contradictions()
        report = ConflictResolver().audit_report(contradictions)
        md = audit_report_markdown(report)
        assert "| fact key | resolved | winner | reason |" in md
        assert "owner" in md
        assert report["resolved"] == 1
        assert f"- total: {report['total']}" in md

    def test_pipe_in_values_is_escaped(self):
        report = {
            "total": 1,
            "resolved": 0,
            "unresolved": 1,
            "by_reason": {},
            "contradictions": [
                {"fact_key": "a|b", "resolved": False, "winner": "x|y", "reason": ""}
            ],
        }
        md = audit_report_markdown(report)
        assert "a\\|b" in md
        # raw pipe would add a column; escaped form keeps the table intact
        row = next(line for line in md.splitlines() if line.startswith("| a"))
        assert row.startswith("| a\\|b |")

    def test_deterministic(self):
        report = {
            "total": 0,
            "resolved": 0,
            "unresolved": 0,
            "by_reason": {"recency": 2},
            "contradictions": [],
        }
        assert audit_report_markdown(report) == audit_report_markdown(report)
        assert "- recency: 2" in audit_report_markdown(report)
