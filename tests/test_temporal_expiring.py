"""Horizon scans for upcoming fact expirations."""

import pytest

from mnemofold.temporal import IntervalFact, TemporalStore, facts_expiring_within

NOW = "2026-03-10T12:00:00+00:00"


def make_store() -> TemporalStore[str]:
    store: TemporalStore[str] = TemporalStore()
    # ends inside the window (in 2 days)
    store.add(
        IntervalFact(
            fact_key="k_soon", value="a", valid_from=NOW, valid_to="2026-03-12T12:00:00+00:00"
        )
    )
    # already ended yesterday
    store.add(
        IntervalFact(
            fact_key="k_past",
            value="b",
            valid_from="2026-03-01T00:00:00+00:00",
            valid_to="2026-03-09T12:00:00+00:00",
        )
    )
    # open-ended
    store.add(IntervalFact(fact_key="k_open", value="c", valid_from=NOW))
    # ends far away (30 days)
    store.add(
        IntervalFact(
            fact_key="k_far", value="d", valid_from=NOW, valid_to="2026-04-09T12:00:00+00:00"
        )
    )
    return store


class TestFactsExpiringWithin:
    def test_only_window_facts_returned(self):
        keys = [f.fact_key for f in facts_expiring_within(make_store(), NOW, days=7.0)]
        assert keys == ["k_soon"]

    def test_wider_horizon_includes_far_fact(self):
        keys = [f.fact_key for f in facts_expiring_within(make_store(), NOW, days=40.0)]
        assert keys == ["k_soon", "k_far"]

    def test_boundary_end_exclusive_at_now(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact(
                fact_key="k", value="v", valid_from="2026-03-01T00:00:00+00:00", valid_to=NOW
            )
        )
        assert facts_expiring_within(store, NOW, days=1.0) == []

    def test_boundary_end_inclusive_at_horizon(self):
        store: TemporalStore[str] = TemporalStore()
        end = "2026-03-11T12:00:00+00:00"
        store.add(IntervalFact(fact_key="k", value="v", valid_from=NOW, valid_to=end))
        assert len(facts_expiring_within(store, NOW, days=1.0)) == 1

    def test_sorted_by_end_then_key(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(
            IntervalFact(
                fact_key="b", value="1", valid_from=NOW, valid_to="2026-03-12T00:00:00+00:00"
            )
        )
        store.add(
            IntervalFact(
                fact_key="a", value="2", valid_from=NOW, valid_to="2026-03-11T00:00:00+00:00"
            )
        )
        facts = facts_expiring_within(store, NOW, days=5)
        assert [f.fact_key for f in facts] == ["a", "b"]

    def test_malformed_valid_to_skipped(self):
        store: TemporalStore[str] = TemporalStore()
        store.add(IntervalFact(fact_key="bad", value="x", valid_from=NOW, valid_to="not-a-date"))
        store.add(
            IntervalFact(
                fact_key="good", value="y", valid_from=NOW, valid_to="2026-03-11T00:00:00+00:00"
            )
        )
        keys = [f.fact_key for f in facts_expiring_within(store, NOW, days=3)]
        assert keys == ["good"]

    def test_negative_window_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            facts_expiring_within(make_store(), NOW, days=-1.0)

    def test_unparseable_now_rejected(self):
        with pytest.raises(ValueError):
            facts_expiring_within(make_store(), "yesterday", days=1.0)

    def test_zero_window_returns_nothing(self):
        assert facts_expiring_within(make_store(), NOW, days=0.0) == []
