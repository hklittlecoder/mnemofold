"""CLI forget --preview: full impact report, zero side effects."""

from mnemofold.cli import main
from mnemofold.factory import WorkHistoryFactory
from mnemofold.memory import MemoryTier
from mnemofold.workspace import Workspace

NOW = "2026-01-05T09:00:00+00:00"


def prepared_db(tmp_path):
    db = tmp_path / "ws"
    factory = WorkHistoryFactory(seed=5, days=3)
    synthetic, _manifest = factory.generate()
    ws = Workspace(db)
    ws.ingest_events([e.to_event() for e in synthetic], now="2026-01-04T12:00:00+00:00")
    target = None
    for tier in MemoryTier:
        items = ws.store.items_by_tier(tier)
        if items:
            target = items[0].item_id
            break
    ws.close()
    assert target is not None
    return db, target


def preview_args(db, target, *extra):
    return ["forget", "--db", str(db), target, "--now", NOW, "--preview", *extra]


class TestForgetPreviewCli:
    def test_preview_reports_and_changes_nothing(self, tmp_path, capsys):
        db, target = prepared_db(tmp_path)
        rc = main(preview_args(db, target))
        out = capsys.readouterr().out
        assert rc == 0
        assert "would delete:" in out
        assert target in out
        assert "nothing was deleted (preview only)" in out
        # the memory is still recallable afterwards
        assert main(["recall", "--db", str(db), target]) == 0

    def test_preview_then_real_forget(self, tmp_path, capsys):
        db, target = prepared_db(tmp_path)
        main(preview_args(db, target))
        capsys.readouterr()
        rc = main(["forget", "--db", str(db), target, "--now", NOW])
        assert rc == 0
        assert "forgotten" in capsys.readouterr().out

    def test_preview_after_forget_plans_nothing(self, tmp_path, capsys):
        db, target = prepared_db(tmp_path)
        main(["forget", "--db", str(db), target, "--now", NOW])
        capsys.readouterr()
        rc = main(preview_args(db, target))
        out = capsys.readouterr().out
        assert rc == 0
        assert "would delete: 0 item(s)" in out

    def test_preview_missing_workspace_errors(self, tmp_path, capsys):
        rc = main(preview_args(tmp_path / "nope", "whatever"))
        assert rc == 1
