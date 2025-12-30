"""Temporal store persistence: golden bytes and query parity."""

from pathlib import Path

import pytest

from mnemofold.persist import PersistError, write_envelope
from mnemofold.temporal import IntervalFact, TemporalStore

FIXTURE = Path(__file__).parent / "fixtures" / "temporal_store_golden.json"


def make_store() -> TemporalStore[str]:
    store: TemporalStore[str] = TemporalStore()
    store.add(
        IntervalFact(
            fact_key="owner",
            value="ana",
            valid_from="2026-01-05T09:00:00+00:00",
            valid_to="2026-02-10T09:00:00+00:00",
        )
    )
    store.add(
        IntervalFact(
            fact_key="owner",
            value="bo",
            valid_from="2026-02-10T09:00:00+00:00",
            metadata={"source": "mail"},
        )
    )
    store.add(
        IntervalFact(fact_key="due", value="2026-03-01", valid_from="2026-01-06T09:00:00+00:00")
    )
    return store


class TestStorePersistence:
    def test_save_matches_golden_bytes(self, tmp_path):
        p = tmp_path / "store.json"
        make_store().save(p)
        assert p.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    def test_load_golden_answers_queries(self):
        store = TemporalStore.load(FIXTURE)
        assert store.as_of("owner", "2026-01-20T00:00:00+00:00").value == "ana"
        assert store.current("owner").value == "bo"
        assert store.current("owner").metadata == {"source": "mail"}
        assert store.keys() == ["due", "owner"]
        assert store.superseded_count() == 1

    def test_roundtrip_preserves_every_query(self, tmp_path):
        store = make_store()
        p = tmp_path / "store.json"
        store.save(p)
        loaded = TemporalStore.load(p)
        assert loaded.to_dict() == store.to_dict()
        for when in (
            "2026-01-10T00:00:00+00:00",
            "2026-02-15T00:00:00+00:00",
            "2026-03-05T00:00:00+00:00",
        ):
            assert loaded.snapshot_at(when).keys() == store.snapshot_at(when).keys()
            for key in store.snapshot_at(when):
                assert loaded.snapshot_at(when)[key].value == (store.snapshot_at(when)[key].value)

    def test_empty_store_roundtrip(self, tmp_path):
        p = tmp_path / "empty.json"
        empty: TemporalStore[str] = TemporalStore()
        empty.save(p)
        assert TemporalStore.load(p).to_dict() == {"facts": []}

    def test_load_rejects_wrong_version(self, tmp_path):
        p = tmp_path / "v2.json"
        write_envelope(p, "temporal_store", {"facts": []}, version=2)
        with pytest.raises(PersistError, match="schema_version"):
            TemporalStore.load(p)

    def test_load_rejects_foreign_schema(self, tmp_path):
        p = tmp_path / "other.json"
        write_envelope(p, "bm25_index", {"docs": {}})
        with pytest.raises(PersistError, match="schema mismatch"):
            TemporalStore.load(p)
