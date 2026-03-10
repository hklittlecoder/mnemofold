"""As-of prep: past packets must not cite future knowledge."""

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.prep import MeetingPrepper

AS_OF = "2026-03-10T12:00:00+00:00"


def item(item_id: str, created: str, text: str = "release sync notes") -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        tier=MemoryTier.EPISODIC,
        content=text,
        title=text,
        created_at=created,
        tags={"note"},
    )


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add(item("old", "2026-03-01T09:00:00+00:00"))
    store.add(item("edge", AS_OF))
    store.add(item("future", "2026-03-20T09:00:00+00:00"))
    store.add(item("noage", ""))
    return store


class TestPrepAsOf:
    def test_future_memories_are_invisible(self):
        prep = MeetingPrepper(store=make_store()).prepare(
            "m1", "release sync", ["ana"], as_of=AS_OF
        )
        ids = {i.item_id for i in prep.items}
        assert "future" not in ids
        assert "noage" not in ids

    def test_past_and_boundary_memories_are_visible(self):
        prep = MeetingPrepper(store=make_store()).prepare(
            "m1", "release sync", ["ana"], as_of=AS_OF
        )
        ids = {i.item_id for i in prep.items}
        assert {"old", "edge"} <= ids

    def test_without_as_of_everything_is_visible(self):
        prep = MeetingPrepper(store=make_store()).prepare("m1", "release sync", ["ana"])
        ids = {i.item_id for i in prep.items}
        assert {"old", "edge", "future", "noage"} <= ids

    def test_naive_as_of_treated_as_utc(self):
        prep = MeetingPrepper(store=make_store()).prepare(
            "m1", "release sync", ["ana"], as_of="2026-03-10T12:00:00"
        )
        ids = {i.item_id for i in prep.items}
        assert "future" not in ids
        assert "old" in ids

    def test_unparseable_as_of_excludes_everything(self):
        prep = MeetingPrepper(store=make_store()).prepare(
            "m1", "release sync", ["ana"], as_of="not-a-date"
        )
        assert prep.items == []

    def test_citations_still_resolve(self):
        store = make_store()
        prep = MeetingPrepper(store=store).prepare("m1", "release sync", ["ana"], as_of=AS_OF)
        for cited in prep.cited_sources:
            assert store.peek(cited) is not None
