"""Visibility is monotone in as_of: time travel never loses evidence.

Prepping the same meeting at successively later instants can only add
cited memories, never remove them — later packets see a superset of
earlier ones.
"""

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.prep import MeetingPrepper

INSTANTS = [
    "2026-03-05T12:00:00+00:00",
    "2026-03-10T12:00:00+00:00",
    "2026-03-15T12:00:00+00:00",
    "2026-03-25T12:00:00+00:00",
]


def make_store() -> MemoryStore:
    store = MemoryStore()
    for i, created in enumerate(INSTANTS):
        store.add(
            MemoryItem(
                item_id=f"m{i}",
                tier=MemoryTier.EPISODIC,
                content="release sync planning notes",
                title="release sync notes",
                created_at=created,
                tags={"note"},
            )
        )
    return store


class TestPrepMonotonicity:
    def test_cited_sets_only_grow(self):
        prepper = MeetingPrepper(store=make_store())
        seen: set[str] = set()
        for instant in INSTANTS:
            prep = prepper.prepare("m", "release sync", ["ana"], as_of=instant)
            ids = {i.item_id for i in prep.items}
            assert seen <= ids, instant
            seen = ids

    def test_final_instant_sees_everything(self):
        prep = MeetingPrepper(store=make_store()).prepare(
            "m", "release sync", ["ana"], as_of=INSTANTS[-1]
        )
        assert {i.item_id for i in prep.items} == {"m0", "m1", "m2", "m3"}

    def test_repeated_prep_is_identical(self):
        prepper = MeetingPrepper(store=make_store())
        a = prepper.prepare("m", "release sync", ["ana"], as_of=INSTANTS[1]).to_dict()
        b = prepper.prepare("m", "release sync", ["ana"], as_of=INSTANTS[1]).to_dict()
        assert a == b
