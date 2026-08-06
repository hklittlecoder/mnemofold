"""Close/reopen parity: queries answer identically after a reopen.

Durability is only real if the reopened workspace behaves the same:
same ask results, same ledger, same fold idempotence, same integrity.
"""

from mnemofold.factory import WorkHistoryFactory
from mnemofold.workspace import Workspace

NOW = "2026-01-10T12:00:00+00:00"


def populated(tmp_path) -> Workspace:
    # no fold here: folding is derived state that rebuilds intentionally
    # drop, so reopen parity is asserted on the journal-backed projections
    factory = WorkHistoryFactory(seed=21, days=7)
    synthetic, _ = factory.generate()
    ws = Workspace(tmp_path / "ws")
    ws.ingest_events([e.to_event() for e in synthetic], now=NOW)
    ws.remember("release checklist for the demo", title="checklist", now=NOW)
    return ws


class TestReopenParity:
    def test_ask_answers_match_across_reopen(self, tmp_path):
        ws = populated(tmp_path)
        before = [(r.item_id, round(r.score, 9)) for r in ws.ask("release", top_k=5)]
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)
        after = [(r.item_id, round(r.score, 9)) for r in reopened.ask("release", top_k=5)]
        assert before == after
        reopened.close()

    def test_fold_after_reopen_reproduces_the_same_report(self, tmp_path):
        ws = populated(tmp_path)
        first = ws.fold("2026-01-11T02:00:00+00:00")
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)  # rebuild restores the pre-fold state
        second = reopened.fold("2026-01-11T02:00:00+00:00")
        assert second.digest() == first.digest()
        reopened.close()

    def test_ledger_survives_reopen(self, tmp_path):
        ws = populated(tmp_path)
        before = ws.ledger.to_json()
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)
        assert reopened.ledger.to_json() == before
        reopened.close()

    def test_integrity_ok_after_reopen(self, tmp_path):
        ws = populated(tmp_path)
        ws_dir = ws.path
        ws.close()
        reopened = Workspace(ws_dir)
        assert reopened.verify_integrity()["ok"] is True
        reopened.close()
