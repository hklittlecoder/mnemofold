"""The eval command surfaces per-project and per-role slice scorecards."""

import json

import pytest

from mnemofold.cli import main


class TestEvalSlices:
    def test_default_has_empty_slices(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "5", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["slices"] == []

    def test_role_slices_in_json(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "20", "--json", "--slices", "roles"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert isinstance(payload["slices"], list)
        for card in payload["slices"]:
            assert "[role:" in card["scenario"]

    def test_project_slices_in_json(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "20", "--json", "--slices", "projects"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        for card in payload["slices"]:
            assert "[role:" not in card["scenario"]

    def test_text_mode_lists_slices(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "20", "--slices", "roles"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "slice commitments[role:" in out

    def test_invalid_choice_rejected(self):
        with pytest.raises(SystemExit):
            main(["eval", "--slices", "galaxies"])
