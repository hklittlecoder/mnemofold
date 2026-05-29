"""Sweep every on-disk artifact after sealed operations for plaintext PII.

Journal, trace, and the full export bundle must all stay clean when the
note was sealed at remember-time — the strongest form of the privacy
tier promise: plaintext never lands at rest anywhere.
"""

from mnemofold.privacy import RedactionVault
from mnemofold.workspace import Workspace

NOW = "2026-03-01T09:00:00+00:00"
SECRET_EMAIL = "ana.chen@corp.example"
SECRET_CARD = "4111 1111 1111 1111"
RAW = f"Mail {SECRET_EMAIL} about card {SECRET_CARD}."


class TestPrivacySweep:
    def test_no_plaintext_in_any_artifact(self, tmp_path):
        wsdir = tmp_path / "ws"
        ws = Workspace(wsdir)
        vault = RedactionVault(salt="sweep-salt")
        ws.remember(RAW, title="contact follow-up", now=NOW, seal_with=vault)
        ws.fold(NOW)
        bundle = tmp_path / "bundle"
        ws.export_bundle(bundle)
        ws.close()

        suspects = [wsdir / "journal.db", wsdir / "trace.jsonl"]
        suspects.extend(sorted(bundle.rglob("*")))
        assert suspects
        for path in suspects:
            if not path.is_file():
                continue
            blob = path.read_bytes()
            assert SECRET_EMAIL.encode() not in blob, path.name
            assert SECRET_CARD.encode() not in blob, path.name

    def test_sealed_content_still_searchable_by_non_pii_terms(self, tmp_path):
        ws = Workspace(tmp_path / "ws")
        vault = RedactionVault(salt="sweep-salt")
        ws.remember(
            "Mail ana.chen@corp.example the release checklist today",
            title="contact",
            now=NOW,
            seal_with=vault,
        )
        hits = ws.ask("release checklist")
        assert hits, "non-PII vocabulary must remain searchable after sealing"
        ws.close()

    def test_vault_file_is_the_only_plaintext_holder(self, tmp_path):
        vault = RedactionVault(salt="sweep-salt")
        sealed = vault.seal(RAW)
        vault_path = tmp_path / "vault.json"
        vault.save(vault_path)
        assert SECRET_EMAIL in vault_path.read_text(encoding="utf-8")
        assert SECRET_EMAIL not in sealed
        assert RedactionVault.load(vault_path).unseal(sealed) == RAW
