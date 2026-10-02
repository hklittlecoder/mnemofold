"""Golden bytes for the contradiction audit report.

The fixture freezes both the resolution outcome (verified source beats
unverified -> ``source_trust``) and the audit report's exact dict form,
so trust-ordering or report-shape drift fails here deliberately.
"""

import json
from pathlib import Path

from mnemofold.canon import canonical_json
from mnemofold.conflict import (
    ConflictResolver,
    EvidenceSource,
    FactEvidence,
)

FIXTURE = Path(__file__).parent / "fixtures" / "conflict_audit_golden.json"

T0 = "2026-03-01T00:00:00+00:00"


def build_report() -> dict:
    resolver = ConflictResolver()
    contradiction = resolver.resolve(
        "owner",
        "ana",
        FactEvidence(source=EvidenceSource.UNVERIFIED, timestamp=T0, source_id="m1"),
        "bo",
        FactEvidence(source=EvidenceSource.VERIFIED, timestamp=T0, source_id="m2"),
    )
    return resolver.audit_report([contradiction])


class TestConflictAuditGolden:
    def test_report_matches_golden_bytes(self):
        assert canonical_json(build_report()) == FIXTURE.read_text(encoding="utf-8")

    def test_winner_and_reason(self):
        report = build_report()
        entry = report["contradictions"][0]
        assert entry["winner"] == "b"
        assert entry["reason"] == "source_trust"

    def test_golden_is_loadable(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert payload["total"] == 1
        assert payload["by_reason"] == {"source_trust": 1}

    def test_regeneration_is_stable(self):
        assert build_report() == build_report()
