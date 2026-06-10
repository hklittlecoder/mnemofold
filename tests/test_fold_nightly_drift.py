"""Two nightly folds over a growing store: the diff tells the story.

Night 1 merges a near-duplicate pair; overnight a new duplicate lands;
night 2 must show exactly that new merge — and an immediate third fold
must show the idempotence signature (no merges added).
"""

from mnemofold.fold import Folder, diff_fold_reports
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


def semantic(store: MemoryStore, item_id: str, content: str, salience: float = 0.5) -> None:
    store.add(
        MemoryItem(
            item_id=item_id,
            tier=MemoryTier.SEMANTIC,
            content=content,
            title=item_id,
            salience=salience,
        )
    )


class TestNightlyDrift:
    def test_second_night_shows_only_the_new_merge(self):
        store = MemoryStore()
        semantic(store, "a1", "quarterly budget review with finance team", 0.6)
        semantic(store, "a2", "quarterly budget review with finance team!", 0.4)
        folder = Folder()
        night1 = folder.fold(store, "2026-03-02T02:00:00+00:00", fold_id="n1")
        assert len(night1.merges) == 1

        semantic(store, "a3", "quarterly budget review with finance team!!", 0.3)
        night2 = folder.fold(store, "2026-03-03T02:00:00+00:00", fold_id="n2")

        diff = diff_fold_reports(night1, night2)
        assert diff["merges_added"] == [
            f"{night2.merges[0].kept_id}->{night2.merges[0].removed_id}"
        ]
        assert diff["merges_removed"] == [
            f"{night1.merges[0].kept_id}->{night1.merges[0].removed_id}"
        ]

    def test_immediate_refold_shows_idempotence_signature(self):
        store = MemoryStore()
        semantic(store, "b1", "release planning notes for q3", 0.6)
        semantic(store, "b2", "release planning notes for q3!", 0.4)
        folder = Folder()
        first = folder.fold(store, "2026-03-02T02:00:00+00:00", fold_id="f1")
        second = folder.fold(store, "2026-03-02T03:00:00+00:00", fold_id="f2")
        assert second.merges == []
        diff = diff_fold_reports(first, second)
        assert diff["merges_added"] == []
        assert len(diff["merges_removed"]) == len(first.merges)
        assert diff["items_after_delta"] == 0

    def test_quiet_nights_diff_empty(self):
        store = MemoryStore()
        semantic(store, "c1", "standalone note about onboarding")
        folder = Folder()
        night1 = folder.fold(store, "2026-03-02T02:00:00+00:00", fold_id="q1")
        night2 = folder.fold(store, "2026-03-03T02:00:00+00:00", fold_id="q2")
        diff = diff_fold_reports(night1, night2)
        assert diff["merges_added"] == []
        assert diff["merges_removed"] == []
        assert diff["new_semantic_added"] == []

    def test_diff_is_deterministic(self):
        store = MemoryStore()
        semantic(store, "d1", "incident postmortem for the march outage", 0.6)
        semantic(store, "d2", "incident postmortem for the march outage!", 0.4)
        folder = Folder()
        n1 = folder.fold(store, "2026-03-02T02:00:00+00:00", fold_id="d1f")
        semantic(store, "d3", "incident postmortem for the march outage!!", 0.3)
        n2 = folder.fold(store, "2026-03-03T02:00:00+00:00", fold_id="d2f")
        assert diff_fold_reports(n1, n2) == diff_fold_reports(n1, n2)
