"""CLI --json output must equal the API-produced dict, deterministically."""

import json

from mnemofold.cli import main
from mnemofold.review import StandupGenerator
from mnemofold.workspace import Workspace

TODAY = "2026-01-04"


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"]) == 0


class TestStandupJsonParity:
    def test_cli_json_equals_direct_generation(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        assert main(["standup", "--db", str(db), "--today", TODAY, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        ws = Workspace(db)
        try:
            data = StandupGenerator(ws.ledger).generate(TODAY)
        finally:
            ws.close()
        assert payload == data.to_dict()

    def test_repeated_runs_are_byte_identical(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        main(["standup", "--db", str(db), "--today", TODAY, "--json"])
        first = capsys.readouterr().out
        main(["standup", "--db", str(db), "--today", TODAY, "--json"])
        second = capsys.readouterr().out
        assert first == second

    def test_citations_reference_ledger_commitments(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        main(["standup", "--db", str(db), "--today", TODAY, "--json"])
        payload = json.loads(capsys.readouterr().out)
        ws = Workspace(db)
        try:
            known = {c.commitment_id for c in ws.ledger.all_commitments()}
        finally:
            ws.close()
        for cited in payload["citations"]:
            assert cited in known or cited.startswith("decision:"), cited
