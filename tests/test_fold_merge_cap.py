"""Merge caps bound one fold without losing deferred candidates."""

from mnemofold.fold import Folder
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier

TS = "2026-03-02T02:00:00+00:00"


def make_store() -> MemoryStore:
    store = MemoryStore()
    base = "release planning notes for q3"
    for i, suffix in enumerate(("", "!", "!!", "!!!")):
        store.add(
            MemoryItem(
                item_id=f"sem-{i}",
                tier=MemoryTier.SEMANTIC,
                content=base + suffix,
                salience=0.5,
            )
        )
    return store


class TestFoldMergeCap:
    def test_cap_limits_merges_in_one_pass(self):
        store = make_store()
        report = Folder(max_merges_per_fold=1).fold(store, TS, fold_id="f1")
        assert len(report.merges) == 1
        capped = [r for r in report.rejected if r["reason"] == "merge_cap_reached"]
        assert capped, "deferred pairs must be reported, not dropped"
        assert store.total_count() == 3

    def test_uncapped_default_merges_all_at_once(self):
        store = make_store()
        report = Folder().fold(store, TS, fold_id="f-all")
        assert len(report.merges) == 3
        assert store.total_count() == 1

    def test_repeated_capped_folds_converge(self):
        capped_store = make_store()
        folder = Folder(max_merges_per_fold=1)
        for i in range(5):
            folder.fold(capped_store, TS, fold_id=f"c{i}")
        uncapped_store = make_store()
        Folder().fold(uncapped_store, TS, fold_id="u")
        assert capped_store.total_count() == uncapped_store.total_count() == 1

    def test_cap_zero_means_unbounded(self):
        store = make_store()
        report = Folder(max_merges_per_fold=0).fold(store, TS, fold_id="z")
        assert len(report.merges) == 3

    def test_capped_fold_is_deterministic(self):
        a = Folder(max_merges_per_fold=2).fold(make_store(), TS, fold_id="d")
        b = Folder(max_merges_per_fold=2).fold(make_store(), TS, fold_id="d")
        assert a.digest() == b.digest()
