"""CLI vault sealing: reversible redaction across invocations."""

from mnemofold.cli import main

RAW = "Mail ana.chen@corp.example or call 555-123-4567."


class TestPrivacyVaultCli:
    def test_seal_creates_vault_and_hides_pii(self, tmp_path, capsys):
        vault = tmp_path / "vault.json"
        rc = main(["privacy", RAW, "--mode", "seal", "--vault", str(vault), "--salt", "s"])
        out = capsys.readouterr().out
        assert rc == 0
        assert vault.exists()
        assert "ana.chen@corp.example" not in out
        assert "<sealed:" in out

    def test_unseal_restores_original(self, tmp_path, capsys):
        vault = tmp_path / "vault.json"
        main(["privacy", RAW, "--mode", "seal", "--vault", str(vault), "--salt", "s"])
        sealed_out = capsys.readouterr().out
        sealed_line = next(ln for ln in sealed_out.splitlines() if ln.startswith("Mail "))
        rc = main(["privacy", sealed_line, "--unseal", "--vault", str(vault)])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == RAW

    def test_second_seal_reuses_vault_tokens(self, tmp_path, capsys):
        vault = tmp_path / "vault.json"
        main(["privacy", RAW, "--mode", "seal", "--vault", str(vault), "--salt", "s"])
        first = capsys.readouterr().out
        main(["privacy", RAW, "--mode", "seal", "--vault", str(vault)])
        second = capsys.readouterr().out
        first_sealed = next(ln for ln in first.splitlines() if ln.startswith("Mail "))
        second_sealed = next(ln for ln in second.splitlines() if ln.startswith("Mail "))
        assert first_sealed == second_sealed

    def test_seal_without_vault_errors(self, tmp_path, capsys):
        rc = main(["privacy", RAW, "--mode", "seal"])
        assert rc == 1
        assert "requires --vault" in capsys.readouterr().err

    def test_unseal_without_vault_errors(self, capsys):
        rc = main(["privacy", "<sealed:email:x>", "--unseal"])
        assert rc == 1
        assert "requires --vault" in capsys.readouterr().err

    def test_unseal_missing_vault_file_errors(self, tmp_path, capsys):
        rc = main(
            ["privacy", "<sealed:email:x>", "--unseal", "--vault", str(tmp_path / "nope.json")]
        )
        assert rc == 1
        assert "vault not found" in capsys.readouterr().err

    def test_mask_mode_unchanged(self, tmp_path, capsys):
        rc = main(["privacy", RAW])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Redacted (mask mode):" in out
