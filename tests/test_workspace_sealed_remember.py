"""Sealed remembering keeps raw PII out of every workspace layer."""

from mnemofold.privacy import RedactionVault
from mnemofold.workspace import Workspace

NOW = "2026-03-01T09:00:00+00:00"
RAW = "Mail ana.chen@corp.example about card 4111 1111 1111 1111."


class TestSealedRemember:
    def test_recalled_content_is_sealed(self, tmp_path):
        ws = Workspace(tmp_path / "ws")
        vault = RedactionVault(salt="s3cret")
        note_id = ws.remember(RAW, title="contact", now=NOW, seal_with=vault)
        item = ws.recall(note_id)
        assert item is not None
        assert "ana.chen@corp.example" not in item.content
        assert "<sealed:" in item.content
        # projection composes content from the payload's string values,
        # so the raw text reappears inside (not as) the unsealed content
        assert RAW in vault.unseal(item.content)
        ws.close()

    def test_title_is_sealed_too(self, tmp_path):
        ws = Workspace(tmp_path / "ws")
        vault = RedactionVault(salt="s3cret")
        note_id = ws.remember("plain body", title="ana.chen@corp.example", now=NOW, seal_with=vault)
        item = ws.recall(note_id)
        assert "ana.chen@corp.example" not in item.title
        ws.close()

    def test_journal_and_trace_bytes_stay_clean(self, tmp_path):
        wsdir = tmp_path / "ws"
        ws = Workspace(wsdir)
        vault = RedactionVault(salt="s3cret")
        ws.remember(RAW, title="contact", now=NOW, seal_with=vault)
        ws.close()
        assert b"ana.chen@corp.example" not in (wsdir / "journal.db").read_bytes()
        assert b"ana.chen@corp.example" not in (wsdir / "trace.jsonl").read_bytes()

    def test_without_vault_text_is_stored_verbatim(self, tmp_path):
        ws = Workspace(tmp_path / "ws")
        note_id = ws.remember(RAW, title="contact", now=NOW)
        item = ws.recall(note_id)
        assert item is not None
        assert RAW in item.content
        ws.close()

    def test_sealing_is_stable_for_same_salt(self, tmp_path):
        first = RedactionVault(salt="same")
        second = RedactionVault(salt="same")
        assert first.seal(RAW) == second.seal(RAW)

    def test_sealed_note_participates_in_integrity(self, tmp_path):
        ws = Workspace(tmp_path / "ws")
        vault = RedactionVault(salt="s3cret")
        note_id = ws.remember(RAW, now=NOW, seal_with=vault)
        ws.forget(note_id, now=NOW)
        report = ws.verify_integrity()
        assert report["ok"] is True
        assert ws.recall(note_id) is None
        ws.close()
