"""The context command's ordering flag reaches the packer."""

import json

import pytest

from mnemofold.cli import main


class TestContextOrdering:
    @pytest.mark.parametrize("ordering", ["priority", "chronological", "category_grouped"])
    def test_ordering_recorded_in_payload(self, capsys, ordering):
        rc = main(["context", "--seed", "5", "--days", "7", "--json", "--ordering", ordering])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["ordering"] == ordering
        assert payload["total_tokens"] <= payload["budget"]

    def test_default_is_priority(self, capsys):
        main(["context", "--seed", "5", "--days", "7", "--json"])
        assert json.loads(capsys.readouterr().out)["ordering"] == "priority"

    def test_invalid_ordering_exits(self):
        with pytest.raises(SystemExit):
            main(["context", "--ordering", "alphabetical"])

    def test_selection_identical_across_orderings(self, capsys):
        # ordering rearranges but must not change WHICH items fit
        sets = []
        for ordering in ("priority", "chronological", "category_grouped"):
            main(
                [
                    "context",
                    "--seed",
                    "5",
                    "--days",
                    "7",
                    "--budget",
                    "500",
                    "--json",
                    "--ordering",
                    ordering,
                ]
            )
            payload = json.loads(capsys.readouterr().out)
            sets.append({item["item_id"] for item in payload["items"]})
        assert sets[0] == sets[1] == sets[2]
