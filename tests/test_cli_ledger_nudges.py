"""The ledger command's nudge listing."""

import json

from mnemofold.cli import main


class TestLedgerNudges:
    def test_text_listing(self, capsys):
        rc = main(["ledger", "--seed", "42", "--days", "45", "--nudges"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Nudges as of" in out

    def test_json_listing_shape(self, capsys):
        rc = main(["ledger", "--seed", "42", "--days", "45", "--nudges", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert isinstance(payload, list)
        for nudge in payload:
            assert set(nudge) == {"commitment_id", "owed_by", "kind", "due_date", "message"}
            assert nudge["kind"] in {"upcoming", "overdue", "blocked"}

    def test_explicit_now_shifts_the_window(self, capsys):
        main(
            [
                "ledger",
                "--seed",
                "42",
                "--days",
                "45",
                "--nudges",
                "--json",
                "--now",
                "2020-01-01T00:00:00+00:00",
            ]
        )
        early = json.loads(capsys.readouterr().out)
        main(
            [
                "ledger",
                "--seed",
                "42",
                "--days",
                "45",
                "--nudges",
                "--json",
                "--now",
                "2030-01-01T00:00:00+00:00",
            ]
        )
        late = json.loads(capsys.readouterr().out)
        # far future: everything is overdue; far past: everything is upcoming
        assert all(n["kind"] == "overdue" for n in late) or late == []
        assert all(n["kind"] != "overdue" for n in early)

    def test_deterministic(self, capsys):
        main(["ledger", "--seed", "42", "--days", "45", "--nudges", "--json"])
        first = capsys.readouterr().out
        main(["ledger", "--seed", "42", "--days", "45", "--nudges", "--json"])
        assert capsys.readouterr().out == first
