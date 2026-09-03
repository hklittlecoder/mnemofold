"""The workspace fold API passes its knobs through to the Folder."""

from mnemofold.memory import MemoryItem, MemoryTier
from mnemofold.workspace import Workspace

NOW = "2026-03-02T02:00:00+00:00"


def ws_with_duplicates(tmp_path) -> Workspace:
    ws = Workspace(tmp_path / "ws")
    for i, suffix in enumerate(("", "!", "?")):
        ws.store.add(
            MemoryItem(
                item_id=f"sem-{i}",
                tier=MemoryTier.SEMANTIC,
                content="quarterly budget review with finance team" + suffix,
                salience=0.5 - i * 0.1,
            )
        )
    return ws


class TestWorkspaceFoldKnobs:
    def test_default_threshold_merges(self, tmp_path):
        ws = ws_with_duplicates(tmp_path)
        report = ws.fold(NOW)
        assert report.merges
        ws.close()

    def test_impossible_threshold_merges_nothing(self, tmp_path):
        ws = ws_with_duplicates(tmp_path)
        report = ws.fold(NOW, similarity_threshold=1.01)
        assert report.merges == []
        assert report.items_after == report.items_before
        ws.close()

    def test_recurrence_floor_respected(self, tmp_path):
        ws = ws_with_duplicates(tmp_path)
        low = ws.fold(NOW, min_episodes_for_recurrence=1)
        ws2 = ws_with_duplicates(tmp_path / "b")
        high = ws2.fold(NOW, min_episodes_for_recurrence=99)
        assert high.recurrence_proposals == []
        assert len(low.recurrence_proposals) >= len(high.recurrence_proposals)
        ws.close()
        ws2.close()

    def test_fold_receipt_records_digest(self, tmp_path):
        from mnemofold.replay import TraceReader

        ws = ws_with_duplicates(tmp_path)
        report = ws.fold(NOW)
        entries = TraceReader(ws.trace.path).entries()
        fold_receipts = [
            e for e in entries if e.kind.value == "receipt" and e.payload.get("action") == "fold"
        ]
        assert fold_receipts
        assert fold_receipts[-1].payload["digest"] == report.digest()
        ws.close()
