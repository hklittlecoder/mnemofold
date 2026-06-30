"""End-to-end core: synthetic history -> extraction -> temporal truth.

One seeded flow exercising the contract between modules: the ingest
pipeline recovers every planted commitment, supersede chains keep
earlier as-of answers frozen, and the interval validator stays clean
over well-formed histories.
"""

from mnemofold.conflict import ConflictResolver, EvidenceSource, FactEvidence
from mnemofold.factory import WorkHistoryFactory
from mnemofold.ingest import IngestPipeline
from mnemofold.temporal import IntervalFact, IntervalValidator, TemporalStore

T0 = "2026-03-01T09:00:00+00:00"
T1 = "2026-03-05T09:00:00+00:00"
T2 = "2026-03-10T09:00:00+00:00"


class TestCorePipeline:
    def test_ingest_recovers_every_planted_commitment(self):
        factory = WorkHistoryFactory(seed=42, days=30)
        synthetic, _manifest = factory.generate()
        typed = [e.to_event() for e in synthetic]
        result = IngestPipeline().run(typed)
        planted = {p.item_id: p.data for p in factory.planted_items() if p.kind == "commitment"}
        assert planted
        extracted = {(c.description, (c.due or "")[:10]) for c in result.commitments}
        for data in planted.values():
            assert (data["description"], data["due_date"][:10]) in extracted

    def test_episodes_cover_all_events_exactly_once(self):
        factory = WorkHistoryFactory(seed=7, days=14)
        synthetic, _ = factory.generate()
        typed = [e.to_event() for e in synthetic]
        result = IngestPipeline().run(typed)
        seen = [e.event_id for ep in result.episodes for e in ep.events]
        assert len(seen) == len(set(seen)) == result.event_count

    def test_supersede_chain_freezes_earlier_answers(self):
        store: TemporalStore[str] = TemporalStore()
        store.supersede("due", "2026-03-01", T0)
        frozen_early = store.snapshot_at(T1)
        store.supersede("due", "2026-03-15", T2)
        store.supersede("due", "2026-03-20", "2026-03-20T09:00:00+00:00")
        after = store.snapshot_at(T1)
        assert after["due"].value == frozen_early["due"].value == "2026-03-01"
        assert store.current("due").value == "2026-03-20"
        assert IntervalValidator().validate(store) == []

    def test_conflict_resolution_keeps_history_queryable(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact(
                fact_key="owner",
                value="ana",
                valid_from=T0,
                valid_to=None,
                metadata={"source": "chat", "source_id": "m1"},
            )
        )
        store.add(
            IntervalFact(
                fact_key="owner",
                value="bo",
                valid_from=T0,
                valid_to=None,
                metadata={"source": "verified_doc", "source_id": "m2"},
            )
        )
        resolver = ConflictResolver()
        contradiction = resolver.resolve(
            "owner",
            "ana",
            FactEvidence(source=EvidenceSource.UNVERIFIED, timestamp=T0, source_id="m1"),
            "bo",
            FactEvidence(source=EvidenceSource.VERIFIED, timestamp=T0, source_id="m2"),
        )
        assert contradiction.resolved
        assert contradiction.winner == "b"  # verified source outranks chat
        resolver.apply_resolution(store, contradiction, superseded_at=T1)
        history = store.history("owner")
        assert len(history) == 2
        loser = next(f for f in history if f.value == "ana")
        assert loser.valid_to == T1
        assert loser.metadata["superseded_by_value"] == "bo"
        winner = next(f for f in history if f.value == "bo")
        assert winner.valid_to is None
