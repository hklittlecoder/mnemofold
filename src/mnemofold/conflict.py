"""Conflict resolution: evidence trust ordering and deterministic supersede.

Handles cases where the same fact key has incompatible values. Uses
evidence trust ordering (verified source, recency, corroboration count),
deterministic supersede policy with tie-breaks, contradiction audit
reports, and a never-lose-history guarantee.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from mnemofold.temporal import IntervalFact, TemporalStore


def confidence_from_evidence(ev: FactEvidence) -> float:
    """Estimate a [0, 1] confidence score from evidence attributes.

    Combines source trust rank (normalized against the maximum rank),
    corroboration count (with diminishing returns via tanh scaling),
    and recency as a small bonus. Quantized to 6 decimals so results
    are stable across Python versions.
    """
    max_rank = max(SOURCE_RANK.values()) if SOURCE_RANK else 1
    trust_component = SOURCE_RANK.get(ev.source, 0) / max_rank
    import math

    corr_component = math.tanh(max(0, ev.corroboration_count) / 3.0)
    weight_trust = 0.7
    weight_corr = 0.3
    score = weight_trust * trust_component + weight_corr * corr_component
    return round(max(0.0, min(1.0, score)), 6)


def _instant_or_min(timestamp: str) -> datetime:
    """Parse an ISO instant for comparisons; unparseable sorts earliest."""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def corroborate(evidences: list[FactEvidence]) -> FactEvidence:
    """Aggregate several pieces of evidence for one value into a single record.

    Deterministic regardless of input order:

    * source: the highest-trust source among the inputs;
    * corroboration_count: every input votes at least once
      (``max(1, count)``), minus the winner's own vote;
    * timestamp: the most recent instant (source_id breaks ties);
    * source_id: from the highest-trust input (earliest id on ties);
    * metadata: merged, plus a sorted ``corroborated_from`` contributor list.
    """
    if not evidences:
        raise ValueError("corroborate requires at least one evidence")
    if len(evidences) == 1:
        return evidences[0]
    best = min(
        evidences,
        key=lambda e: (-SOURCE_RANK.get(e.source, 0), e.source_id, e.timestamp),
    )
    latest = max(evidences, key=lambda e: (_instant_or_min(e.timestamp), e.source_id))
    votes = sum(max(1, e.corroboration_count) for e in evidences) - 1
    metadata: dict[str, Any] = {}
    for evidence in evidences:
        for key, value in evidence.metadata.items():
            metadata.setdefault(key, value)
    metadata["corroborated_from"] = sorted({e.source_id for e in evidences if e.source_id})
    return FactEvidence(
        source=best.source,
        timestamp=latest.timestamp,
        source_id=best.source_id,
        corroboration_count=votes,
        metadata=metadata,
    )


class EvidenceSource(StrEnum):
    """Trust levels for evidence sources."""

    VERIFIED = "verified"
    TRUSTED = "trusted"
    DEFAULT = "default"
    UNVERIFIED = "unverified"
    SPECULATIVE = "speculative"


SOURCE_RANK: dict[EvidenceSource, int] = {
    EvidenceSource.VERIFIED: 50,
    EvidenceSource.TRUSTED: 40,
    EvidenceSource.DEFAULT: 30,
    EvidenceSource.UNVERIFIED: 20,
    EvidenceSource.SPECULATIVE: 10,
}


@dataclass(slots=True)
class FactEvidence:
    """Evidence supporting a fact value."""

    source: EvidenceSource
    timestamp: str
    source_id: str = ""
    corroboration_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.source, str):
            self.source = EvidenceSource(self.source)


@dataclass(slots=True)
class Contradiction:
    """A detected contradiction between two fact versions."""

    fact_key: str
    value_a: Any
    value_b: Any
    evidence_a: FactEvidence
    evidence_b: FactEvidence
    resolved: bool = False
    winner: str | None = None
    resolution_reason: str = ""


@dataclass(slots=True)
class ConflictResolver:
    """Resolves conflicting fact values using evidence trust ordering.

    Resolution policy (in order of precedence):
    1. Higher source trust level wins
    2. More corroborating evidence wins
    3. More recent timestamp wins
    4. Deterministic value-hash tie-break

    The loser is never deleted — it remains in the temporal store as a
    superseded fact, queryable via as-of for the period it was active.
    """

    def evidence_score(self, ev: FactEvidence) -> tuple[int, int, str, str]:
        """Compute evidence score tuple for deterministic comparison."""
        return (
            SOURCE_RANK.get(ev.source, 0),
            ev.corroboration_count,
            ev.timestamp,
            ev.source_id,
        )

    def resolve(
        self,
        fact_key: str,
        value_a: Any,
        evidence_a: FactEvidence,
        value_b: Any,
        evidence_b: FactEvidence,
    ) -> Contradiction:
        """Resolve a contradiction between two fact versions."""
        contradiction = Contradiction(
            fact_key=fact_key,
            value_a=value_a,
            value_b=value_b,
            evidence_a=evidence_a,
            evidence_b=evidence_b,
        )
        if value_a == value_b:
            contradiction.resolved = True
            contradiction.winner = "a"
            contradiction.resolution_reason = "identical_values"
            return contradiction

        score_a = self.evidence_score(evidence_a)
        score_b = self.evidence_score(evidence_b)

        if score_a > score_b:
            contradiction.resolved = True
            contradiction.winner = "a"
            contradiction.resolution_reason = self._reason(score_a, score_b)
        elif score_b > score_a:
            contradiction.resolved = True
            contradiction.winner = "b"
            contradiction.resolution_reason = self._reason(score_b, score_a)
        else:
            ha = hashlib.sha256(str(value_a).encode()).hexdigest()
            hb = hashlib.sha256(str(value_b).encode()).hexdigest()
            if ha >= hb:
                contradiction.resolved = True
                contradiction.winner = "a"
            else:
                contradiction.resolved = True
                contradiction.winner = "b"
            contradiction.resolution_reason = "deterministic_tiebreak"
        return contradiction

    def _reason(self, winner_score: tuple, loser_score: tuple) -> str:
        if winner_score[0] > loser_score[0]:
            return "source_trust"
        if winner_score[1] > loser_score[1]:
            return "corroboration"
        if winner_score[2] > loser_score[2]:
            return "recency"
        if winner_score[3] > loser_score[3]:
            return "source_id"
        return "tiebreak"

    def resolve_many(
        self,
        candidates: list[tuple[str, Any, FactEvidence, Any, FactEvidence]],
    ) -> list[Contradiction]:
        """Resolve multiple candidate contradictions in one pass.

        ``candidates`` is a list of ``(fact_key, value_a, evidence_a,
        value_b, evidence_b)`` tuples. Resolution order matches input
        order so the audit trail is deterministic.
        """
        return [self.resolve(key, va, ea, vb, eb) for key, va, ea, vb, eb in candidates]

    def apply_resolution(
        self,
        store: TemporalStore,
        contradiction: Contradiction,
        superseded_at: str,
    ) -> None:
        """Apply a resolution: mark the losing fact as superseded."""
        if not contradiction.resolved:
            return
        losing_value = (
            contradiction.value_a if contradiction.winner == "b" else contradiction.value_b
        )
        hist = store.history(contradiction.fact_key)
        for fact in reversed(hist):
            if fact.value == losing_value and fact.is_current():
                fact.valid_to = superseded_at
                winner_val = (
                    contradiction.value_b if contradiction.winner == "b" else contradiction.value_a
                )
                fact.metadata["superseded_by_value"] = str(winner_val)
                fact.metadata["resolution_reason"] = contradiction.resolution_reason
                break

    def audit_report(self, contradictions: list[Contradiction]) -> dict[str, Any]:
        """Generate an audit report for a list of contradictions."""
        resolved = [c for c in contradictions if c.resolved]
        unresolved = [c for c in contradictions if not c.resolved]
        by_reason: dict[str, int] = {}
        for c in resolved:
            by_reason[c.resolution_reason] = by_reason.get(c.resolution_reason, 0) + 1
        return {
            "total": len(contradictions),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "by_reason": by_reason,
            "contradictions": [
                {
                    "fact_key": c.fact_key,
                    "resolved": c.resolved,
                    "winner": c.winner,
                    "reason": c.resolution_reason,
                }
                for c in contradictions
            ],
        }


# --- Contradiction scanning over temporal stores ------------------------------


def _fact_interval(fact: IntervalFact[Any]) -> tuple[datetime, datetime]:
    """Half-open [start, end) interval of a fact; open-ended ends at max."""
    start = _instant_or_min(fact.valid_from)
    end = (
        _instant_or_min(fact.valid_to)
        if fact.valid_to is not None
        else datetime.max.replace(tzinfo=UTC)
    )
    return start, end


def _evidence_from_fact(fact: IntervalFact[Any]) -> FactEvidence:
    """Derive evidence from a fact's metadata (source, source_id, corroboration)."""
    metadata = dict(fact.metadata)
    source_value = metadata.get("source", EvidenceSource.DEFAULT)
    try:
        source = EvidenceSource(source_value)
    except ValueError:
        source = EvidenceSource.DEFAULT
    count = metadata.get("corroboration", 0)
    return FactEvidence(
        source=source,
        timestamp=fact.valid_from,
        source_id=str(metadata.get("source_id", "")),
        corroboration_count=count if isinstance(count, int) else 0,
        metadata=metadata,
    )


@dataclass(slots=True)
class ConflictDetector:
    """Finds fact keys whose versions claim overlapping periods.

    Two versions of one fact key conflict when their validity intervals
    overlap and their values differ. Each conflicting pair is resolved
    through the standard evidence-trust ordering. History is never
    destroyed: ``scan_and_apply`` closes the loser's interval at the
    supersede instant, so as-of queries for earlier time keep answering
    with the superseded value.
    """

    resolver: ConflictResolver = field(default_factory=ConflictResolver)

    def scan(self, store: TemporalStore[Any]) -> list[Contradiction]:
        """All overlapping incompatible value pairs, in key/history order."""
        found: list[Contradiction] = []
        fact_keys = store.keys()  # bound first: the store is not a dict
        for fact_key in fact_keys:
            versions = store.history(fact_key)
            for earlier, later in itertools.combinations(versions, 2):
                if earlier.value == later.value:
                    continue
                e_start, e_end = _fact_interval(earlier)
                l_start, l_end = _fact_interval(later)
                if not (e_start < l_end and l_start < e_end):
                    continue
                found.append(
                    self.resolver.resolve(
                        fact_key,
                        earlier.value,
                        _evidence_from_fact(earlier),
                        later.value,
                        _evidence_from_fact(later),
                    )
                )
        return found

    def scan_and_apply(self, store: TemporalStore[Any], superseded_at: str) -> list[Contradiction]:
        """Scan and immediately supersede every losing fact version."""
        contradictions = self.scan(store)
        for contradiction in contradictions:
            self.resolver.apply_resolution(store, contradiction, superseded_at)
        return contradictions


def _md_cell(value: object) -> str:
    """Escape a value for one Markdown table cell."""
    return str(value).replace("|", "\\|")


def audit_report_markdown(report: dict[str, Any]) -> str:
    """Deterministic Markdown rendering of an :meth:`audit_report` dict.

    Sections: totals, resolutions by reason, and one table row per
    contradiction citing its fact key, winner and reason — the same
    fields the resolver recorded, nothing invented. Pipe characters in
    values are escaped so hostile fact keys cannot break the table.
    """
    lines = [
        "# Contradiction Audit",
        "",
        f"- total: {report.get('total', 0)}",
        f"- resolved: {report.get('resolved', 0)}",
        f"- unresolved: {report.get('unresolved', 0)}",
        "",
        "## Resolutions by reason",
        "",
    ]
    by_reason = report.get("by_reason", {})
    if by_reason:
        for reason in sorted(by_reason):
            lines.append(f"- {reason}: {by_reason[reason]}")
    else:
        lines.append("- (none)")
    lines.extend(["", "## Contradictions", ""])
    entries = report.get("contradictions", [])
    if entries:
        lines.append("| fact key | resolved | winner | reason |")
        lines.append("| --- | --- | --- | --- |")
        for c in entries:
            lines.append(
                f"| {_md_cell(c.get('fact_key', ''))} "
                f"| {_md_cell(c.get('resolved', False))} "
                f"| {_md_cell(c.get('winner', ''))} "
                f"| {_md_cell(c.get('reason', ''))} |"
            )
    else:
        lines.append("_No contradictions recorded._")
    return "\n".join(lines)
