"""The ask command's per-term BM25 explanation surface."""

import json

import pytest

from mnemofold.cli import main
from mnemofold.retrieval import tokenize

pytestmark = pytest.mark.slow


def ingest(db, days: int = 14) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", str(days)]) == 0


class TestAskExplain:
    def test_json_payload_carries_explanations(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["ask", "--db", str(db), "milestone", "--json", "--explain"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload, "seeded history must contain 'milestone' matches"
        for entry in payload:
            assert "explain" in entry
            for part in entry["explain"]:
                assert set(part) == {"term", "tf", "df", "idf", "contribution"}
                assert part["contribution"] >= 0.0

    def test_explain_terms_come_from_the_query(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        main(["ask", "--db", str(db), "milestone", "--json", "--explain"])
        payload = json.loads(capsys.readouterr().out)
        allowed = set(tokenize("milestone"))
        for entry in payload:
            for part in entry["explain"]:
                assert part["term"] in allowed

    def test_text_mode_prints_term_lines(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["ask", "--db", str(db), "milestone", "--explain"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "term 'milestone'" in out

    def test_without_explain_payload_is_unchanged(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        main(["ask", "--db", str(db), "milestone", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert all("explain" not in entry for entry in payload)

    def test_filters_do_not_leak_into_explain_terms(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        main(["ask", "--db", str(db), "milestone tag:note", "--json", "--explain"])
        payload = json.loads(capsys.readouterr().out)
        for entry in payload:
            for part in entry["explain"]:
                assert part["term"] != "tag"
                assert part["term"] != "note" or "note" in tokenize("milestone")
