"""Supersede semantics: close-and-open without losing as-of answers."""

from mnemofold.temporal import IntervalFact, IntervalValidator, TemporalStore

T0 = "2026-01-05T09:00:00+00:00"
T1 = "2026-02-10T09:00:00+00:00"
T2 = "2026-03-15T09:00:00+00:00"


def make_store() -> TemporalStore[str]:
    store: TemporalStore[str] = TemporalStore()
    store.add(IntervalFact(fact_key="owner", value="ana", valid_from=T0))
    return store


class TestSupersede:
    def test_first_supersede_closes_previous_version(self):
        store = make_store()
        store.supersede("owner", "bo", T1)
        old = store.history("owner")[0]
        assert old.valid_to == T1
        assert store.current("owner").value == "bo"

    def test_as_of_before_boundary_keeps_old_value(self):
        store = make_store()
        store.supersede("owner", "bo", T1)
        assert store.as_of("owner", "2026-01-20T00:00:00+00:00").value == "ana"
        assert store.as_of("owner", T1).value == "bo"  # valid_from is inclusive

    def test_supersede_without_existing_fact_starts_history(self):
        store: TemporalStore[str] = TemporalStore()
        fact = store.supersede("due", "2026-03-01", T0)
        assert fact.valid_from == T0
        assert store.current("due").value == "2026-03-01"
        assert store.superseded_count() == 0

    def test_chained_supersedes_keep_full_history(self):
        store = make_store()
        store.supersede("owner", "bo", T1)
        store.supersede("owner", "cy", T2)
        history = store.history("owner")
        assert [f.value for f in history] == ["ana", "bo", "cy"]
        assert history[0].valid_to == T1
        assert history[1].valid_to == T2
        assert history[2].valid_to is None
        assert store.superseded_count() == 2
        assert IntervalValidator().validate(store) == []

    def test_metadata_is_attached(self):
        store = make_store()
        store.supersede("owner", "bo", T1, metadata={"source": "mail"})
        assert store.current("owner").metadata == {"source": "mail"}

    def test_supersede_returns_the_new_fact(self):
        store = make_store()
        fact = store.supersede("owner", "bo", T1)
        assert fact is store.current("owner")

    def test_backdated_supersede_is_flagged_not_rewritten(self):
        store = make_store()
        store.supersede("owner", "bo", T1)
        # superseding with an instant before the current start creates
        # overlaps; the store does not hide them — the validator reports
        # both the ana/late overlap and the open-ended late/bo overlap
        store.supersede("owner", "late", "2026-01-20T00:00:00+00:00")
        violations = IntervalValidator().validate(store)
        assert len(violations) == 2
        assert {v.fact_key for v in violations} == {"owner"}
