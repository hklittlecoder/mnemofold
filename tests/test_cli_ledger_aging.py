"""The ledger command's aging report mode."""

import json

from mnemofold.cli import main


class TestLedgerAgingCli:
    def test_text_report(self, capsys):
        rc = main(["ledger", "--seed", "5", "--days", "30", "--aging"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Ledger aging as of" in out
        for bucket in ("overdue:", "due_today:", "due_this_week:", "later:", "no_due:"):
            assert bucket in out
        assert "total active:" in out

    def test_json_report(self, capsys):
        rc = main(["ledger", "--seed", "5", "--days", "30", "--aging", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert set(payload) >= {
            "now",
            "total_active",
            "counts",
            "overdue",
            "due_today",
            "due_this_week",
            "later",
            "no_due",
        }
        assert sum(payload["counts"].values()) == payload["total_active"]

    def test_aging_counts_match_listed_ids(self, capsys):
        main(["ledger", "--seed", "11", "--days", "45", "--aging", "--json"])
        payload = json.loads(capsys.readouterr().out)
        for bucket in ("overdue", "due_today", "due_this_week", "later", "no_due"):
            assert len(payload[bucket]) == payload["counts"][bucket]

    def test_plain_mode_unchanged(self, capsys):
        rc = main(["ledger", "--seed", "5", "--days", "14"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "# Commitment Ledger" in out
        assert "Total:" in out
