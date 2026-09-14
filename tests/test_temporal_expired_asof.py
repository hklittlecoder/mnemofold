"""Listing a fact as expired must never remove it from as-of answers.

The audit view is read-only; the temporal contract (history is never
lost) has to hold before and after the listing is computed.
"""

from mnemofold.temporal import TemporalStore, facts_expired_at

T0 = "2026-03-01T00:00:00+00:00"
T1 = "2026-03-05T00:00:00+00:00"
NOW = "2026-03-10T12:00:00+00:00"


def make_store() -> TemporalStore[str]:
    store: TemporalStore[str] = TemporalStore()
    store.supersede("owner", "ana", T0)
    store.supersede("owner", "bo", T1)
    return store


class TestExpiredVsAsOf:
    def test_superseded_fact_listed_but_still_answered(self):
        store = make_store()
        expired = facts_expired_at(store, NOW)
        assert [f.value for f in expired] == ["ana"]
        # the as-of answer from before the supersede is unchanged
        assert store.as_of("owner", "2026-03-03T00:00:00+00:00").value == "ana"
        assert store.current("owner").value == "bo"

    def test_listing_twice_changes_nothing(self):
        store = make_store()
        first = facts_expired_at(store, NOW)
        second = facts_expired_at(store, NOW)
        assert [f.value for f in first] == [f.value for f in second]
        assert store.as_of("owner", "2026-03-03T00:00:00+00:00").value == "ana"

    def test_open_current_fact_never_listed(self):
        store = make_store()
        expired_keys = {f.fact_key for f in facts_expired_at(store, NOW)}
        assert "owner" in expired_keys  # the OLD version expired...
        current = store.current("owner")
        assert current is not None and current.valid_to is None  # ...this one hasn't
        assert current not in facts_expired_at(store, NOW)
