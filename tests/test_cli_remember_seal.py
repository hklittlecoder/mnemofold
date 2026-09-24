"""CLI-side sealed remembering: vault file lifecycle and clean journals."""

from mnemofold.cli import main
from mnemofold.privacy import RedactionVault

NOW = "2026-03-01T09:00:00+00:00"
RAW = "Mail ana.chen@corp.example about card 4111 1111 1111 1111."


class TestRememberSeal:
    def test_seal_requires_vault(self, tmp_path, capsys):
        rc = main(["remember", "--db", str(tmp_path / "ws"), "--text", RAW, "--now", NOW, "--seal"])
        assert rc == 1
        assert "--seal requires --vault" in capsys.readouterr().err

    def test_sealed_note_creates_vault_and_hides_pii(self, tmp_path, capsys):
        db = tmp_path / "ws"
        vault = tmp_path / "vault.json"
        rc = main(
            [
                "remember",
                "--db",
                str(db),
                "--text",
                RAW,
                "--now",
                NOW,
                "--seal",
                "--vault",
                str(vault),
                "--salt",
                "cli-salt",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        item_id = out.split()[1]
        assert vault.exists()
        # journal and trace never saw the raw values
        assert b"ana.chen@corp.example" not in (db / "journal.db").read_bytes()
        assert b"ana.chen@corp.example" not in (db / "trace.jsonl").read_bytes()
        # the vault can still restore them
        loaded = RedactionVault.load(vault)
        rc = main(["recall", "--db", str(db), item_id, "--json"])
        import json

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert "ana.chen@corp.example" not in payload["content"]
        assert RAW in loaded.unseal(payload["content"])

    def test_unsealed_remember_unchanged(self, tmp_path, capsys):
        db = tmp_path / "ws"
        rc = main(["remember", "--db", str(db), "--text", RAW, "--now", NOW])
        assert rc == 0
        assert "remembered " in capsys.readouterr().out
        assert b"ana.chen@corp.example" in (db / "journal.db").read_bytes()

    def test_vault_reused_across_invocations(self, tmp_path, capsys):
        db = tmp_path / "ws"
        vault = tmp_path / "vault.json"
        main(
            [
                "remember",
                "--db",
                str(db),
                "--text",
                RAW,
                "--now",
                NOW,
                "--seal",
                "--vault",
                str(vault),
                "--salt",
                "cli-salt",
            ]
        )
        capsys.readouterr()
        # second note reuses the vault: same value -> same token
        main(
            [
                "remember",
                "--db",
                str(db),
                "--text",
                RAW + " Again.",
                "--now",
                "2026-03-01T10:00:00+00:00",
                "--seal",
                "--vault",
                str(vault),
            ]
        )
        assert main(["verify", "--db", str(db)]) == 0
        capsys.readouterr()
        loaded = RedactionVault.load(vault)
        assert loaded.seal(RAW) == loaded.seal(RAW)
