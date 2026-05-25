"""Triage result serialization and the CLI --json surface."""

import json

from mnemofold.cli import main
from mnemofold.triage import TriagePriority, TriageResult


class TestTriageResultToDict:
    def test_shape_and_quantization(self):
        r = TriageResult(
            item_id="i1",
            score=0.1234567891,
            priority=TriagePriority.URGENT,
            reasons=["due soon", "explicit ask"],
        )
        d = r.to_dict()
        assert d == {
            "item_id": "i1",
            "score": 0.123457,
            "priority": "urgent",
            "reasons": ["due soon", "explicit ask"],
        }

    def test_reasons_list_is_copied(self):
        r = TriageResult(item_id="i1", score=0.5, priority=TriagePriority.LOW, reasons=["a"])
        d = r.to_dict()
        d["reasons"].append("injected")
        assert r.to_dict()["reasons"] == ["a"]


class TestTriageCliJson:
    def test_json_output_parses(self, capsys):
        rc = main(["triage", "--seed", "5", "--days", "7", "--top", "3", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["shown"] <= 3
        assert payload["scored"] >= payload["shown"]
        for entry in payload["top"]:
            assert {"item_id", "score", "priority", "reasons", "title", "sender"} <= set(entry)

    def test_scores_are_sorted_desc(self, capsys):
        main(["triage", "--seed", "5", "--days", "14", "--top", "10", "--json"])
        payload = json.loads(capsys.readouterr().out)
        scores = [e["score"] for e in payload["top"]]
        assert scores == sorted(scores, reverse=True)

    def test_text_mode_unchanged(self, capsys):
        rc = main(["triage", "--seed", "5", "--days", "7"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Inbox Triage" in out
        assert "Scored" in out
