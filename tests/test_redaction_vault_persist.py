"""Redaction vault persistence: sealed text survives a restart."""

import pytest

from mnemofold.persist import PersistError
from mnemofold.privacy import RedactionVault

SECRET = "Contact ana@corp.example or +1-555-0100 for the release."


class TestVaultSerde:
    def test_roundtrip_restores_unseal(self, tmp_path):
        vault = RedactionVault(salt="s3cret")
        sealed = vault.seal(SECRET)
        assert "ana@corp.example" not in sealed
        p = tmp_path / "vault.json"
        vault.save(p)
        loaded = RedactionVault.load(p)
        assert loaded.salt == "s3cret"
        assert loaded.unseal(sealed) == SECRET

    def test_to_dict_carries_salt_and_tokens(self):
        vault = RedactionVault(salt="k")
        vault.seal(SECRET)
        d = vault.to_dict()
        assert d["salt"] == "k"
        assert set(d["tokens"]) == set(vault.known_tokens())

    def test_from_dict_matches_sealed_count(self):
        vault = RedactionVault(salt="k")
        vault.seal(SECRET)
        rebuilt = RedactionVault.from_dict(vault.to_dict())
        assert rebuilt.sealed_count() == vault.sealed_count()
        assert rebuilt.known_tokens() == vault.known_tokens()

    def test_save_bytes_are_deterministic(self, tmp_path):
        a = RedactionVault(salt="k")
        a.seal(SECRET)
        b = RedactionVault(salt="k")
        b.seal(SECRET)
        pa, pb = tmp_path / "a.json", tmp_path / "b.json"
        a.save(pa)
        b.save(pb)
        assert pa.read_bytes() == pb.read_bytes()

    def test_load_rejects_foreign_schema(self, tmp_path):
        from mnemofold.persist import write_envelope

        p = tmp_path / "bad.json"
        write_envelope(p, "not_a_vault", {"salt": "", "tokens": {}})
        with pytest.raises(PersistError, match="schema mismatch"):
            RedactionVault.load(p)

    def test_different_salt_produces_different_tokens(self):
        a = RedactionVault(salt="alpha")
        b = RedactionVault(salt="beta")
        assert a.seal(SECRET) != b.seal(SECRET)
        # a token sealed under one salt cannot be unsealed by the other
        sealed = a.seal(SECRET)
        assert b.unseal(sealed) == sealed
