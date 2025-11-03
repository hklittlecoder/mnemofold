"""Tests for conflict resolution."""

from __future__ import annotations

from mnemofold.conflict import (
    ConflictDetector,
    ConflictResolver,
    Contradiction,
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

    def test_source_id_tiebreak_when_other_fields_equal(self):
        r = ConflictResolver()
        ev_a = FactEvidence(
            EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "alpha", corroboration_count=2
        )
        ev_b = FactEvidence(
            EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "beta", corroboration_count=2
        )
        c = r.resolve("k", "val_a", ev_a, "val_b", ev_b)
        assert c.resolution_reason == "source_id"
        assert c.winner == "b"

    def test_deterministic_tiebreak(self):
        r = ConflictResolver()
        ev = FactEvidence(EvidenceSource.DEFAULT, "2024-01-01T00:00:00+00:00", "s")
        c1 = r.resolve("k", "val_a", ev, "val_b", ev)
        c2 = r.resolve("k", "val_a", ev, "val_b", ev)
        assert c1.winner == c2.winner
        assert c1.resolution_reason == "deterministic_tiebreak"

    def test_resolve_many_preserves_order(self):
        r = ConflictResolver()
        ev_v = FactEvidence(EvidenceSource.VERIFIED, "2024-01-01T00:00:00+00:00", "s1")
        ev_u = FactEvidence(EvidenceSource.UNVERIFIED, "2024-06-01T00:00:00+00:00", "s2")
        candidates = [
            ("k1", "a", ev_v, "b", ev_u),
            ("k2", "x", ev_u, "y", ev_v),
            ("k3", "same", ev_v, "same", ev_u),
        ]
        results = r.resolve_many(candidates)
        assert len(results) == 3
        assert results[0].fact_key == "k1" and results[0].winner == "a"
        assert results[1].fact_key == "k2" and results[1].winner == "b"
        assert results[2].fact_key == "k3" and results[2].resolution_reason == "identical_values"

    def test_resolve_many_empty(self):
        r = ConflictResolver()
        assert r.resolve_many([]) == []

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


class TestConflictDetector:
    def _conflicting_store(self) -> TemporalStore:
        store: TemporalStore = TemporalStore()
        store.add(
            IntervalFact(
                "owner",
                "alice",
                "2025-01-01T00:00:00+00:00",
                metadata={"source": "trusted", "source_id": "mail-1"},
            )
        )
        store.add(
            IntervalFact(
                "owner",
                "bob",
                "2025-02-01T00:00:00+00:00",
                metadata={"source": "verified", "source_id": "hr-2"},
            )
        )
        return store

    def test_overlapping_conflict_detected_with_winner(self):
        found = ConflictDetector().scan(self._conflicting_store())
        assert len(found) == 1
        assert found[0].fact_key == "owner"
        assert found[0].winner == "b"
        assert found[0].resolution_reason == "source_trust"

    def test_sequential_versions_do_not_conflict(self):
        store: TemporalStore = TemporalStore()
        store.add(
            IntervalFact("owner", "alice", "2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00")
        )
        store.add(IntervalFact("owner", "bob", "2025-02-01T00:00:00+00:00"))
        assert ConflictDetector().scan(store) == []

    def test_identical_values_never_conflict(self):
        store: TemporalStore = TemporalStore()
        store.add(IntervalFact("owner", "alice", "2025-01-01T00:00:00+00:00"))
        store.add(IntervalFact("owner", "alice", "2025-02-01T00:00:00+00:00"))
        assert ConflictDetector().scan(store) == []

    def test_corroboration_metadata_breaks_source_ties(self):
        store: TemporalStore = TemporalStore()
        store.add(
            IntervalFact(
                "owner",
                "alice",
                "2025-01-01T00:00:00+00:00",
                metadata={"source": "trusted", "corroboration": 5},
            )
        )
        store.add(
            IntervalFact(
                "owner",
                "bob",
                "2025-02-01T00:00:00+00:00",
                metadata={"source": "trusted", "corroboration": 0},
            )
        )
        found = ConflictDetector().scan(store)
        assert found[0].winner == "a"
        assert found[0].resolution_reason == "corroboration"

    def test_scan_and_apply_preserves_as_of_history(self):
        store = self._conflicting_store()
        found = ConflictDetector().scan_and_apply(store, "2025-02-01T00:00:00+00:00")
        assert len(found) == 1
        # loser interval closed, but the past stays queryable
        past = store.as_of("owner", "2025-01-15T00:00:00+00:00")
        assert past is not None and past.value == "alice"
        present = store.current("owner")
        assert present is not None and present.value == "bob"
        history = store.history("owner")
        assert history[0].metadata["superseded_by_value"] == "bob"

    def test_clean_tiling_after_apply_at_boundary(self):
        store = self._conflicting_store()
        detector = ConflictDetector()
        detector.scan_and_apply(store, "2025-02-01T00:00:00+00:00")
        # loser now ends exactly where the winner starts -> no overlap left
        assert detector.scan(store) == []

    def test_keys_scanned_in_sorted_order(self):
        store: TemporalStore = TemporalStore()
        for key in ("zeta", "alpha"):
            store.add(IntervalFact(key, "one", "2025-01-01T00:00:00+00:00"))
            store.add(IntervalFact(key, "two", "2025-01-02T00:00:00+00:00"))
        found = ConflictDetector().scan(store)
        assert [c.fact_key for c in found] == ["alpha", "zeta"]

    def test_unknown_source_metadata_falls_back_to_default(self):
        store: TemporalStore = TemporalStore()
        store.add(
            IntervalFact(
                "owner", "alice", "2025-01-01T00:00:00+00:00", metadata={"source": "rumor-mill"}
            )
        )
        store.add(
            IntervalFact(
                "owner", "bob", "2025-02-01T00:00:00+00:00", metadata={"source": "verified"}
            )
        )
        found = ConflictDetector().scan(store)
        assert found[0].winner == "b"


class TestResolutionRules:
    def _evidence(
        self,
        source=EvidenceSource.DEFAULT,
        timestamp="2025-01-01T00:00:00+00:00",
        source_id="s",
        count=0,
    ) -> FactEvidence:
        return FactEvidence(
            source=source, timestamp=timestamp, source_id=source_id, corroboration_count=count
        )

    def test_source_rank_ordering(self):
        scores = [
            ConflictResolver().evidence_score(self._evidence(source=s))[0]
            for s in (
                EvidenceSource.VERIFIED,
                EvidenceSource.TRUSTED,
                EvidenceSource.DEFAULT,
                EvidenceSource.UNVERIFIED,
                EvidenceSource.SPECULATIVE,
            )
        ]
        assert scores == sorted(scores, reverse=True)
        assert len(set(scores)) == 5

    def test_reason_precedence_corroboration(self):
        resolver = ConflictResolver()
        c = resolver.resolve("k", "a", self._evidence(count=3), "b", self._evidence(count=1))
        assert c.winner == "a"
        assert c.resolution_reason == "corroboration"

    def test_reason_precedence_recency(self):
        resolver = ConflictResolver()
        c = resolver.resolve(
            "k",
            "a",
            self._evidence(timestamp="2025-01-01T00:00:00+00:00"),
            "b",
            self._evidence(timestamp="2025-02-01T00:00:00+00:00"),
        )
        assert c.winner == "b"
        assert c.resolution_reason == "recency"

    def test_reason_precedence_source_id(self):
        resolver = ConflictResolver()
        c = resolver.resolve(
            "k", "a", self._evidence(source_id="aaa"), "b", self._evidence(source_id="bbb")
        )
        assert c.winner == "b"
        assert c.resolution_reason == "source_id"

    def test_identical_values_short_circuit(self):
        c = ConflictResolver().resolve("k", "same", self._evidence(), "same", self._evidence())
        assert c.resolved
        assert c.winner == "a"
        assert c.resolution_reason == "identical_values"

    def test_hash_tiebreak_is_symmetric_in_value(self):
        resolver = ConflictResolver()
        forward = resolver.resolve("k", "x", self._evidence(), "y", self._evidence())
        swapped = resolver.resolve("k", "y", self._evidence(), "x", self._evidence())
        assert forward.resolution_reason == "deterministic_tiebreak"
        winning_forward = forward.value_a if forward.winner == "a" else forward.value_b
        winning_swapped = swapped.value_a if swapped.winner == "a" else swapped.value_b
        assert winning_forward == winning_swapped

    def test_hash_tiebreak_is_stable_across_runs(self):
        first = ConflictResolver().resolve("k", "x", self._evidence(), "y", self._evidence())
        second = ConflictResolver().resolve("k", "x", self._evidence(), "y", self._evidence())
        assert first.winner == second.winner


class TestAuditReport:
    def test_report_counts_and_reasons(self):
        resolver = ConflictResolver()
        evidence = FactEvidence(
            source=EvidenceSource.DEFAULT, timestamp="2025-01-01T00:00:00+00:00"
        )
        strong = FactEvidence(source=EvidenceSource.VERIFIED, timestamp="2025-01-01T00:00:00+00:00")
        contradictions = [
            resolver.resolve("k1", "a", strong, "b", evidence),
            resolver.resolve("k2", "same", evidence, "same", evidence),
            Contradiction(
                fact_key="k3",
                value_a="x",
                value_b="y",
                evidence_a=evidence,
                evidence_b=evidence,
            ),  # left unresolved on purpose
        ]
        report = resolver.audit_report(contradictions)
        assert report["total"] == 3
        assert report["resolved"] == 2
        assert report["unresolved"] == 1
        assert report["by_reason"] == {"source_trust": 1, "identical_values": 1}
        assert len(report["contradictions"]) == 3

    def test_empty_report(self):
        report = ConflictResolver().audit_report([])
        assert report == {
            "total": 0,
            "resolved": 0,
            "unresolved": 0,
            "by_reason": {},
            "contradictions": [],
        }
