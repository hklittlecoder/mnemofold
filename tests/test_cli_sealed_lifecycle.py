"""Full CLI lifecycle over a sealed note: ask, forget, verify, export."""

import json

from mnemofold.cli import main

NOW = "2026-03-01T09:00:00+00:00"
LATER = "2026-03-02T09:00:00+00:00"
RAW = "Ping bo.li@corp.example about the release checklist"


def seal_note(tmp_path, capsys):
    db = tmp_path / "ws"
    vault = tmp_path / "vault.json"
    main(
        [
            "remember",
            "--db",
            str(db),
            "--text",
            RAW,
            "--title",
            "checklist",
            "--now",
            NOW,
            "--seal",
            "--vault",
            str(vault),
            "--salt",
            "s",
        ]
    )
    out = capsys.readouterr().out
    return db, vault, out.split()[1]


class TestSealedLifecycle:
    def test_sealed_note_is_searchable_by_non_pii_words(self, tmp_path, capsys):
        db, _vault, _item = seal_note(tmp_path, capsys)
        capsys.readouterr()
        rc = main(["ask", "--db", str(db), "release checklist", "--json"])
        hits = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert hits, "non-PII vocabulary must remain searchable"

    def test_forget_with_preview_then_verify(self, tmp_path, capsys):
        db, _vault, item = seal_note(tmp_path, capsys)
        capsys.readouterr()
        rc = main(["forget", "--db", str(db), item, "--now", LATER, "--preview"])
        out = capsys.readouterr().out
        assert rc == 0
        assert item in out
        rc = main(["forget", "--db", str(db), item, "--now", LATER, "--report", "json"])
        report = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert report["requested_key"] == item
        rc = main(["verify", "--db", str(db), "--json"])
        integrity = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert integrity["ok"] is True
        assert integrity["tombstones"] >= 1

    def test_export_bundle_contains_no_plaintext(self, tmp_path, capsys):
        db, _vault, _item = seal_note(tmp_path, capsys)
        capsys.readouterr()
        bundle = tmp_path / "bundle"
        assert main(["export", "--db", str(db), "--bundle", str(bundle)]) == 0
        capsys.readouterr()
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                assert b"bo.li@corp.example" not in path.read_bytes(), path.name
