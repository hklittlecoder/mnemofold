"""Expired-fact audits: boundaries, ordering, malformed data."""

import pytest

from mnemofold.temporal import (
    IntervalFact,
    TemporalStore,
    facts_expired_at,
    facts_expiring_within,
)

NOW = "2026-03-10T12:00:00+00:00"


def make_store() -> TemporalStore[str]:
    store: TemporalStore[str] = TemporalStore()
    store.add(
        IntervalFact(
            fact_key="k_past",
            value="a",
            valid_from="2026-03-01T00:00:00+00:00",
            valid_to="2026-03-05T00:00:00+00:00",
        )
    )
    store.add(
        IntervalFact(
            fact_key="k_edge", value="b", valid_from="2026-03-08T00:00:00+00:00", valid_to=NOW
        )
    )
    store.add(IntervalFact(fact_key="k_open", value="c", valid_from="2026-03-09T00:00:00+00:00"))
    store.add(
        IntervalFact(
            fact_key="k_future_end",
            value="d",
            valid_from="2026-03-09T00:00:00+00:00",
            valid_to="2026-03-20T00:00:00+00:00",
        )
    )
    store.add(
        IntervalFact(
            fact_key="k_bad",
            value="e",
            valid_from="2026-03-09T00:00:00+00:00",
            valid_to="not-a-date",
        )
    )
    return store


class TestFactsExpiredAt:
    def test_past_and_edge_included_future_and_open_excluded(self):
        keys = [f.fact_key for f in facts_expired_at(make_store(), NOW)]
        assert keys == ["k_past", "k_edge"]

    def test_boundary_is_inclusive_at_now(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact(
                fact_key="k", value="v", valid_from="2026-03-01T00:00:00+00:00", valid_to=NOW
            )
        )
        assert len(facts_expired_at(store, NOW)) == 1
        earlier = "2026-03-09T23:59:59+00:00"
        assert facts_expired_at(store, earlier) == []

    def test_sorted_by_end_then_key(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact(
                fact_key="b",
                value="1",
                valid_from="2026-03-01T00:00:00+00:00",
                valid_to="2026-03-05T00:00:00+00:00",
            )
        )
        store.add(
            IntervalFact(
                fact_key="a",
                value="2",
                valid_from="2026-03-01T00:00:00+00:00",
                valid_to="2026-03-04T00:00:00+00:00",
            )
        )
        keys = [f.fact_key for f in facts_expired_at(store, NOW)]
        assert keys == ["a", "b"]

    def test_malformed_valid_to_skipped(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact(
                fact_key="bad",
                value="x",
                valid_from="2026-03-01T00:00:00+00:00",
                valid_to="garbage",
            )
        )
        assert facts_expired_at(store, NOW) == []

    def test_unparseable_now_raises(self):
        with pytest.raises(ValueError):
            facts_expired_at(make_store(), "yesterday")

    def test_complements_expiring_within(self):
        store = make_store()
        expired = {f.fact_key for f in facts_expired_at(store, NOW)}
        upcoming = {f.fact_key for f in facts_expiring_within(store, NOW, days=30.0)}
        assert expired.isdisjoint(upcoming)
        assert "k_future_end" in upcoming
