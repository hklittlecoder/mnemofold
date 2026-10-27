"""A corrupted workspace must produce clean CLI errors, never tracebacks.

Tampering the persisted trace makes the fail-fast resume refuse to open
the workspace; every --db command routes through the same opener, so
they must all report the corruption and exit non-zero.
"""

import json

from mnemofold.cli import main


def ingest(db) -> None:
    assert main(["ingest", "--db", str(db), "--seed", "5", "--days", "3"]) == 0


def corrupt_trace(db) -> None:
    trace = db / "trace.jsonl"
    lines = trace.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["entry"]["payload"]["tampered"] = True
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
    trace.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestCorruptedWorkspace:
    def test_verify_reports_corruption(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        corrupt_trace(db)
        rc = main(["verify", "--db", str(db)])
        err = capsys.readouterr().err
        assert rc == 1
        assert "workspace corrupted" in err

    def test_recall_reports_corruption(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        corrupt_trace(db)
        rc = main(["recall", "--db", str(db), "anything"])
        assert rc == 1
        assert "workspace corrupted" in capsys.readouterr().err

    def test_session_reports_corruption(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        corrupt_trace(db)
        rc = main(["session", "--db", str(db), "--json"])
        assert rc == 1
        assert "workspace corrupted" in capsys.readouterr().err

    def test_healthy_workspace_unaffected(self, tmp_path, capsys):
        db = tmp_path / "ws"
        ingest(db)
        capsys.readouterr()
        rc = main(["verify", "--db", str(db), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["ok"] is True
