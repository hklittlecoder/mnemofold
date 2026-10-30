"""The eval command's noise sweep flag."""

import json

import pytest

from mnemofold.cli import main

pytestmark = pytest.mark.slow


class TestEvalNoise:
    def test_json_payload_includes_sweep(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "20", "--json", "--noise", "0,0.5"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert [c["details"]["noise_level"] for c in payload["noise_sweep"]] == [0.0, 0.5]
        for card in payload["noise_sweep"]:
            values = {m["name"]: m["value"] for m in card["metrics"]}
            assert 0.0 <= values["noisy_commitment_recall"] <= 1.0

    def test_text_mode_prints_levels(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "20", "--noise", "0"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "noise 0.0: recall=" in out

    def test_default_has_no_sweep(self, capsys):
        main(["eval", "--seed", "3", "--days", "5", "--json"])
        assert json.loads(capsys.readouterr().out)["noise_sweep"] == []

    def test_bad_noise_value_exits_2(self, capsys):
        rc = main(["eval", "--seed", "3", "--days", "5", "--noise", "loud"])
        assert rc == 2
        assert "--noise" in capsys.readouterr().err

    def test_sweep_is_deterministic(self, capsys):
        main(["eval", "--seed", "3", "--days", "20", "--json", "--noise", "0.25"])
        first = json.loads(capsys.readouterr().out)["noise_sweep"]
        main(["eval", "--seed", "3", "--days", "20", "--json", "--noise", "0.25"])
        assert json.loads(capsys.readouterr().out)["noise_sweep"] == first
