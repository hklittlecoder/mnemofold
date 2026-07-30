"""Argument-level contract: bad choices and missing args exit non-zero.

Complements the missing-workspace sweep: these are argparse and
command-level validation paths users hit when scripting mnemofold.
"""

import pytest

from mnemofold.cli import main

NOW = "2026-01-05T09:00:00+00:00"


class TestCliErrorContract:
    def test_privacy_without_text_errors(self, capsys):
        rc = main(["privacy"])
        assert rc == 1
        assert "provide text" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv",
        [
            ["export", "--db", "x", "--format", "xml"],
            ["forget", "--db", "x", "id", "--now", NOW, "--report", "yaml"],
            ["eval", "--slices", "galaxies"],
            ["privacy", "text", "--mode", "shred"],
        ],
    )
    def test_invalid_choices_exit(self, argv):
        with pytest.raises(SystemExit):
            main(argv)

    @pytest.mark.parametrize(
        "argv",
        [
            ["standup"],
            ["review", "--db", "x", "--start", NOW],
            ["ask", "--db", "x"],
            ["remember", "--db", "x", "--text", "t"],
            ["forget", "--db", "x", "id"],
        ],
    )
    def test_missing_required_args_exit(self, argv):
        with pytest.raises(SystemExit):
            main(argv)

    def test_unseal_without_vault_errors(self, capsys):
        rc = main(["privacy", "<sealed:email:x>", "--unseal"])
        assert rc == 1
        assert "requires --vault" in capsys.readouterr().err
