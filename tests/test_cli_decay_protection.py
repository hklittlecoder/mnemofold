"""Held and pinned content must survive even aggressive CLI decay."""

import json

from mnemofold.cli import main
from mnemofold.workspace import Workspace

OLD = "2026-01-01T09:00:00+00:00"
LATER = "2028-01-01T09:00:00+00:00"  # two years later: everything ages out


class TestDecayProtection:
    def test_legal_hold_tag_is_protected(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert (
            main(
                [
                    "remember",
                    "--db",
                    str(db),
                    "--text",
                    "audit evidence",
                    "--tags",
                    "legal_hold",
                    "--now",
                    OLD,
                ]
            )
            == 0
        )
        capsys.readouterr()
        rc = main(["decay", "--db", str(db), "--now", LATER, "--json"])
        counters = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert counters["protected_skipped"] >= 1
        # the held memory is still recallable after the pass
        ws = Workspace(db)
        try:
            held = [
                item
                for tier_items in (ws.store.items_by_tier(t) for t in ws.store.tier_counts())
                for item in tier_items
                if "legal_hold" in item.tags
            ]
            assert held, "legal-hold memory must survive decay"
        finally:
            ws.close()

    def test_unheld_memories_do_age(self, tmp_path, capsys):
        db = tmp_path / "ws"
        assert main(["remember", "--db", str(db), "--text", "scratch note", "--now", OLD]) == 0
        capsys.readouterr()
        main(["decay", "--db", str(db), "--now", LATER, "--json"])
        counters = json.loads(capsys.readouterr().out)
        assert counters["demoted"] + counters["purged"] + counters["tombstoned"] >= 1

    def test_integrity_holds_after_decay(self, tmp_path, capsys):
        db = tmp_path / "ws"
        main(["ingest", "--db", str(db), "--seed", "5", "--days", "7"])
        capsys.readouterr()
        main(["decay", "--db", str(db), "--now", LATER])
        capsys.readouterr()
        rc = main(["verify", "--db", str(db), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["ok"] is True
