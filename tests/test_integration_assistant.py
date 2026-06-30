"""End-to-end assistant flow: ingest -> fold -> pack -> report -> audit.

A single workspace session exercises the full assistant loop and the
cross-module invariants that bind it: packs respect budgets, citations
resolve to live memories, reports cite ids that exist, and the closing
integrity audit passes over everything the session did.
"""

import json

from mnemofold.context import PackingProfile
from mnemofold.factory import WorkHistoryFactory
from mnemofold.review import WeeklyReviewGenerator, compare_reviews
from mnemofold.workspace import Workspace

NOW = "2025-01-12T18:00:00+00:00"


def make_workspace(tmp_path) -> Workspace:
    factory = WorkHistoryFactory(seed=15, days=14)
    synthetic, _ = factory.generate()
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events([e.to_event() for e in synthetic], now=NOW)
    return ws


class TestAssistantFlow:
    def test_full_session_holds_every_invariant(self, tmp_path):
        ws = make_workspace(tmp_path)

        # fold consolidates and reports
        report = ws.fold(NOW)
        assert report.items_before >= report.items_after

        # context packs never exceed budget and cite live memories
        pack = ws.context_pack(
            "milestone release", budget_tokens=300, profile=PackingProfile.MEETING_PREP, now=NOW
        )
        assert pack.total_tokens <= pack.budget
        for item in pack.items:
            assert ws.recall(item.item_id) is not None

        # ask citations resolve
        hits = ws.ask("release", top_k=5, now=NOW)
        for hit in hits:
            assert ws.recall(hit.item_id) is not None

        # reports render and cite
        standup = ws.standup("2025-01-12", now=NOW)
        assert standup.date == "2025-01-12"
        week1 = WeeklyReviewGenerator(ws.ledger).generate(
            "2025-01-01T00:00:00+00:00", "2025-01-08T00:00:00+00:00"
        )
        week2 = WeeklyReviewGenerator(ws.ledger).generate(
            "2025-01-08T00:00:00+00:00", "2025-01-15T00:00:00+00:00"
        )
        delta = compare_reviews(week1, week2)
        assert isinstance(delta["stats_delta"], dict)

        # bundle is self-describing and matches live state
        manifest = ws.export_bundle(tmp_path / "bundle")
        assert manifest["events"] == len(ws.journal)
        assert (
            json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
            == manifest
        )

        # everything still verifies after the whole session
        integrity = ws.verify_integrity()
        assert integrity["ok"] is True
        assert integrity["journal"]["frames"] == len(ws.journal)
        ws.close()

    def test_forget_mid_session_keeps_invariants(self, tmp_path):
        ws = make_workspace(tmp_path)
        ws.fold(NOW)
        victim = ws.ask("release", top_k=1, now=NOW)
        if victim:
            target = victim[0].item_id
            preview = ws.forget_preview(target)
            ws.forget(target, now=NOW)
            assert ws.recall(target) is None
            assert ws.forget_preview(target)["would_delete"] == []
            # pack after forget still cites only live memories
            pack = ws.context_pack("release", budget_tokens=300, now=NOW)
            for item in pack.items:
                assert item.item_id != target
                assert ws.recall(item.item_id) is not None
            assert preview["total"] >= 0
        assert ws.verify_integrity()["ok"] is True
        ws.close()
