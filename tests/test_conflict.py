"""Tests for conflict resolution."""

from __future__ import annotations

from mnemofold.conflict import (
    ConflictResolver,
    EvidenceSource,
    FactEvidence,
    corroborate,
)
from mnemofold.temporal import IntervalFact, TemporalStore


class TestEvidenceSource:
    def test_all_ranks_defined(self):
        from mnemofold.conflict import SOURCE_RANK

        for src in EvidenceSource:
            assert src in SOURCE_RANK

    def test_rank_ordering(self):
        from mnemofold.conflict import SOURCE_RANK

        assert SOURCE_RANK[EvidenceSource.VERIFIED] > SOURCE_RANK[EvidenceSource.TRUSTED]
        assert SOURCE_RANK[EvidenceSource.TRUSTED] > SOURCE_RANK[EvidenceSource.DEFAULT]
        assert SOURCE_RANK[EvidenceSource.DEFAULT] > SOURCE_RANK[EvidenceSource.UNVERIFIED]
        assert SOURCE_RANK[EvidenceSource.UNVERIFIED] > SOURCE_RANK[EvidenceSource.SPECULATIVE]


class TestConflictResolver:
    def test_identical_values(self):
        r = ConflictResolver()
        ev = FactEvidence(EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "s")
        c = r.resolve("k", "v", ev, "v", ev)
        assert c.resolved
        assert c.resolution_reason == "identical_values"

    def test_source_trust_wins(self):
        r = ConflictResolver()
        ev_v = FactEvidence(EvidenceSource.VERIFIED, "2024-01-01T00:00:00+00:00", "s")
        ev_u = FactEvidence(EvidenceSource.UNVERIFIED, "2024-06-01T00:00:00+00:00", "s2")
        c = r.resolve("k", "v1", ev_v, "v2", ev_u)
        assert c.resolved
        assert c.winner == "a"
        assert c.resolution_reason == "source_trust"

    def test_corroboration_wins(self):
        r = ConflictResolver()
        ev1 = FactEvidence(
            EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "s", corroboration_count=1
        )
        ev5 = FactEvidence(
            EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "s", corroboration_count=5
        )
        c = r.resolve("k", "a", ev1, "b", ev5)
        assert c.winner == "b"
        assert c.resolution_reason == "corroboration"

    def test_recency_wins(self):
        r = ConflictResolver()
        ev_old = FactEvidence(EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "s")
        ev_new = FactEvidence(EvidenceSource.DEFAULT, "2024-06-01T00:00:00+00:00", "s")
        c = r.resolve("k", "old", ev_old, "new", ev_new)
        assert c.winner == "b"
        assert c.resolution_reason == "recency"

    def test_deterministic_tiebreak(self):
        r = ConflictResolver()
        ev = FactEvidence(EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "s")
        c1 = r.resolve("k", "val_a", ev, "val_b", ev)
        c2 = r.resolve("k", "val_a", ev, "val_b", ev)
        assert c1.winner == c2.winner
        assert c1.resolution_reason == "deterministic_tiebreak"

    def test_apply_resolution_supersedes_loser(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("owner", "alice", "2024-01-01T00:00:00+00:00"))
        store.add(IntervalFact("owner", "bob", "2024-03-01T00:00:00+00:00"))
        r = ConflictResolver()
        ev_a = FactEvidence(EvidenceSource.VERIFIED, "2024-01-01T00:00:00+00:00", "hr")
        ev_b = FactEvidence(EvidenceSource.UNVERIFIED, "2024-03-01T00:00:00+00:00", "rumor")
        c = r.resolve("owner", "alice", ev_a, "bob", ev_b)
        r.apply_resolution(store, c, "2024-03-15T00:00:00+00:00")
        bob_facts = [f for f in store.history("owner") if f.value == "bob"]
        assert bob_facts and bob_facts[-1].valid_to is not None

    def test_as_of_still_works_after_supersede(self):
        store = TemporalStore[str]()
        store.add(IntervalFact("owner", "old", "2024-01-01T00:00:00+00:00"))
        store.add(IntervalFact("owner", "new", "2024-06-01T00:00:00+00:00"))
        # Query old time should still return old value (never-lose-history)
        fact = store.as_of("owner", "2024-03-01T00:00:00+00:00")
        assert fact is not None
        assert fact.value == "old"

    def test_audit_report(self):
        r = ConflictResolver()
        contradictions = []
        for i in range(3):
            ev_a = FactEvidence(EvidenceSource.VERIFIED, "2024-01-01T00:00:00+00:00", f"s{i}")
            ev_b = FactEvidence(EvidenceSource.SPECULATIVE, "2024-06-01T00:00:00+00:00", f"s{i}")
            contradictions.append(r.resolve(f"k{i}", f"a{i}", ev_a, f"b{i}", ev_b))
        report = r.audit_report(contradictions)
        assert report["total"] == 3
        assert report["resolved"] == 3
        assert report["by_reason"]["source_trust"] == 3


class TestCorroboration:
    def _evidence(self, source, timestamp, source_id="", count=0, **metadata) -> FactEvidence:
        return FactEvidence(
            source=source,
            timestamp=timestamp,
            source_id=source_id,
            corroboration_count=count,
            metadata=dict(metadata),
        )

    def test_single_evidence_passes_through(self):
        only = self._evidence(EvidenceSource.TRUSTED, "2025-01-01T00:00:00+00:00")
        assert corroborate([only]) is only

    def test_empty_input_raises(self):
        import pytest

        with pytest.raises(ValueError, match="at least one"):
            corroborate([])

    def test_highest_trust_wins_regardless_of_order(self):
        weak = self._evidence(EvidenceSource.SPECULATIVE, "2025-01-02T00:00:00+00:00", "w")
        strong = self._evidence(EvidenceSource.VERIFIED, "2025-01-01T00:00:00+00:00", "s")
        forward = corroborate([weak, strong])
        backward = corroborate([strong, weak])
        assert forward.source == EvidenceSource.VERIFIED
        assert forward.source_id == "s"
        assert (forward.source, forward.source_id) == (backward.source, backward.source_id)

    def test_votes_accumulate_with_at_least_one_each(self):
        a = self._evidence(EvidenceSource.DEFAULT, "2025-01-01T00:00:00+00:00", count=0)
        b = self._evidence(EvidenceSource.DEFAULT, "2025-01-02T00:00:00+00:00", count=0)
        assert corroborate([a, b]).corroboration_count == 1
        c = self._evidence(EvidenceSource.DEFAULT, "2025-01-01T00:00:00+00:00", count=3)
        d = self._evidence(EvidenceSource.DEFAULT, "2025-01-02T00:00:00+00:00", count=2)
        assert corroborate([c, d]).corroboration_count == 4

    def test_most_recent_timestamp_wins_across_offsets(self):
        # 09:00-05:00 == 14:00Z, later than 12:00Z though its string sorts first
        early = self._evidence(EvidenceSource.DEFAULT, "2025-01-01T12:00:00+00:00", "e")
        late = self._evidence(EvidenceSource.DEFAULT, "2025-01-01T09:00:00-05:00", "l")
        merged = corroborate([early, late])
        assert merged.timestamp == "2025-01-01T09:00:00-05:00"

    def test_rank_ties_break_on_source_id(self):
        b_evidence = self._evidence(EvidenceSource.TRUSTED, "2025-01-01T00:00:00+00:00", "bbb")
        a_evidence = self._evidence(EvidenceSource.TRUSTED, "2025-01-02T00:00:00+00:00", "aaa")
        assert corroborate([b_evidence, a_evidence]).source_id == "aaa"

    def test_metadata_merged_with_contributor_list(self):
        a = self._evidence(
            EvidenceSource.DEFAULT, "2025-01-01T00:00:00+00:00", "src-a", note="first"
        )
        b = self._evidence(EvidenceSource.DEFAULT, "2025-01-02T00:00:00+00:00", "src-b", extra=2)
        merged = corroborate([a, b])
        assert merged.metadata["note"] == "first"
        assert merged.metadata["extra"] == 2
        assert merged.metadata["corroborated_from"] == ["src-a", "src-b"]

    def test_aggregation_is_order_independent(self):
        a = self._evidence(EvidenceSource.TRUSTED, "2025-01-01T00:00:00+00:00", "a", count=2)
        b = self._evidence(EvidenceSource.VERIFIED, "2025-01-03T00:00:00+00:00", "b", count=1)
        c = self._evidence(EvidenceSource.DEFAULT, "2025-01-02T00:00:00+00:00", "c", count=5)
        forward = corroborate([a, b, c])
        backward = corroborate([c, b, a])
        assert (
            forward.source,
            forward.timestamp,
            forward.source_id,
            forward.corroboration_count,
        ) == (
            backward.source,
            backward.timestamp,
            backward.source_id,
            backward.corroboration_count,
        )
