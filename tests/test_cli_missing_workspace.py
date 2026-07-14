"""One contract, every read-side --db command: missing workspace => rc 1.

A single parametrized sweep instead of per-command copies: any new
workspace-backed subcommand should join this list and inherit the
behavior users rely on for scripting. ``remember`` is the documented
exception — it bootstraps a fresh workspace instead of failing.
"""

import pytest

from mnemofold.cli import main

NOW = "2026-01-05T09:00:00+00:00"
WEEK = ("2025-01-01T00:00:00+00:00", "2025-01-08T00:00:00+00:00")


def cases(missing: str) -> list[list[str]]:
    return [
        ["export", "--db", missing],
        ["forget", "--db", missing, "item-1", "--now", NOW],
        ["recall", "--db", missing, "item-1"],
        ["ask", "--db", missing, "hello"],
        ["standup", "--db", missing],
        ["review", "--db", missing, "--start", WEEK[0], "--end", WEEK[1]],
        ["playbooks", "--db", missing],
        ["verify", "--db", missing],
    ]


@pytest.mark.parametrize("index", range(8))
def test_missing_workspace_contract(tmp_path, capsys, index):
    argv = cases(str(tmp_path / "does-not-exist"))[index]
    rc = main(argv)
    err = capsys.readouterr().err
    assert rc == 1, argv
    assert "workspace not found" in err, argv


def test_remember_bootstraps_a_new_workspace(tmp_path, capsys):
    db = tmp_path / "fresh"
    rc = main(["remember", "--db", str(db), "--text", "first note", "--now", NOW])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("remembered ")
    assert db.is_dir()
    # and the bootstrapped workspace satisfies the read-side commands
    assert main(["recall", "--db", str(db), out.split()[1]]) == 0
