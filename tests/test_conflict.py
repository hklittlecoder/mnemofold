"""Tests for conflict resolution."""

from __future__ import annotations

from mnemofold.conflict import (
    ConflictResolver,
    EvidenceSource,
    FactEvidence,
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
