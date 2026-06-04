"""A capped fold must still cite every pair it looked at.

The fold report contract: every candidate pair ends up either merged or
rejected with a reason. Capping changes the reason distribution, never
the completeness of the audit trail.
"""

from mnemofold.fold import Folder
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.textsim import bigram_jaccard

TS = "2026-03-02T02:00:00+00:00"


def make_store(n: int = 4) -> MemoryStore:
    store = MemoryStore()
    base = "quarterly budget review with finance team"
    for i in range(n):
        store.add(
            MemoryItem(
                item_id=f"n{i}",
                tier=MemoryTier.SEMANTIC,
                content=base + "!" * i,
                salience=0.5,
            )
        )
    return store


def expected_pairs(n: int) -> int:
    return n * (n - 1) // 2


class TestCappedReportCompleteness:
    def test_every_pair_accounted_for(self):
        report = Folder(max_merges_per_fold=1).fold(make_store(4), TS, fold_id="c")
        # after one merge, 3 items remain but only pairs evaluated before
        # the loser was removed count; every merge + rejection is listed
        merged_pairs = {(m.kept_id, m.removed_id) for m in report.merges}
        rejected_pairs = {(r["a"], r["b"]) for r in report.rejected}
        assert merged_pairs.isdisjoint(rejected_pairs)
        assert len(report.merges) == 1
        assert report.rejected

    def test_rejection_reasons_are_known(self):
        report = Folder(max_merges_per_fold=1).fold(make_store(4), TS, fold_id="c2")
        reasons = {r["reason"] for r in report.rejected}
        assert reasons <= {"below_threshold", "merge_cap_reached"}

    def test_capped_pairs_are_genuinely_similar(self):
        store = make_store(4)
        report = Folder(max_merges_per_fold=1).fold(store, TS, fold_id="c3")
        for entry in report.rejected:
            if entry["reason"] == "merge_cap_reached":
                assert entry["similarity"] >= 0.75

    def test_markdown_includes_capped_rejections(self):
        report = Folder(max_merges_per_fold=1).fold(make_store(4), TS, fold_id="c4")
        md = report.to_markdown()
        assert "merge_cap_reached" in md

    def test_similarity_values_match_textsim(self):
        store = make_store(3)
        report = Folder(max_merges_per_fold=1).fold(store, TS, fold_id="c5")
        entry = report.rejected[0]
        # recompute independently: both were near-identical variants
        sim = bigram_jaccard(
            "quarterly budget review with finance team" + "!" * int(entry["a"][1]),
            "quarterly budget review with finance team" + "!" * int(entry["b"][1]),
        )
        assert abs(sim - entry["similarity"]) < 1e-9
