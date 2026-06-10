"""Fold report diffs: drift views between nightly runs."""

from mnemofold.fold import FoldReport, MergeResult, diff_fold_reports


def report(fold_id: str, merges=None, new_semantic=None, proposals=None) -> FoldReport:
    return FoldReport(
        fold_id=fold_id,
        timestamp="2026-03-02T02:00:00+00:00",
        items_before=10,
        items_after=10 - len(merges or []),
        merges=list(merges or []),
        new_semantic=list(new_semantic or []),
        recurrence_proposals=list(proposals or []),
    )


def merge(kept: str, removed: str) -> MergeResult:
    return MergeResult(kept_id=kept, removed_id=removed, reason="near_duplicate", similarity=0.9)


class TestFoldDiff:
    def test_identical_reports_diff_empty(self):
        r = report("f1", merges=[merge("a", "b")], new_semantic=["s1"])
        diff = diff_fold_reports(r, r)
        assert diff["merges_added"] == []
        assert diff["merges_removed"] == []
        assert diff["new_semantic_added"] == []
        assert diff["items_after_delta"] == 0

    def test_added_and_removed_merges(self):
        base = report("f1", merges=[merge("a", "b")])
        cand = report("f2", merges=[merge("c", "d")])
        diff = diff_fold_reports(base, cand)
        assert diff["merges_added"] == ["c->d"]
        assert diff["merges_removed"] == ["a->b"]

    def test_new_semantic_movement(self):
        base = report("f1", new_semantic=["s1", "s2"])
        cand = report("f2", new_semantic=["s2", "s3"])
        diff = diff_fold_reports(base, cand)
        assert diff["new_semantic_added"] == ["s3"]
        assert diff["new_semantic_removed"] == ["s1"]

    def test_proposals_compared_by_content(self):
        base = report("f1", proposals=[{"kind": "workflow_sequence", "workflow": "release"}])
        cand = report("f2", proposals=[{"kind": "workflow_sequence", "workflow": "deploy"}])
        diff = diff_fold_reports(base, cand)
        assert len(diff["proposals_added"]) == 1
        assert len(diff["proposals_removed"]) == 1
        assert "deploy" in diff["proposals_added"][0]

    def test_items_after_delta(self):
        base = report("f1", merges=[merge("a", "b")])
        cand = report("f2")
        assert diff_fold_reports(base, cand)["items_after_delta"] == 1

    def test_fold_ids_recorded(self):
        diff = diff_fold_reports(report("night-1"), report("night-2"))
        assert diff["baseline_fold_id"] == "night-1"
        assert diff["candidate_fold_id"] == "night-2"
