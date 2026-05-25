"""Context pack serialization and the CLI --json surface."""

import json

from mnemofold.cli import main
from mnemofold.context import ContextItem, ContextPack, PackingProfile


def make_pack() -> ContextPack:
    return ContextPack(
        items=[
            ContextItem(
                item_id="m1",
                content="Release checklist draft",
                title="Release checklist",
                token_estimate=12,
                priority=0.75123456,
                category="commitment",
            ),
        ],
        total_tokens=12,
        budget=100,
        profile=PackingProfile.MEETING_PREP,
    )


class TestPackToDict:
    def test_shape_and_quantization(self):
        d = make_pack().to_dict()
        assert d["profile"] == "meeting_prep"
        assert d["ordering"] == "priority"
        assert d["budget"] == 100
        assert d["total_tokens"] == 12
        assert d["headroom"] == 88
        assert d["items"][0]["priority"] == 0.751235

    def test_json_serializable_and_deterministic(self):
        a = json.dumps(make_pack().to_dict(), sort_keys=True)
        b = json.dumps(make_pack().to_dict(), sort_keys=True)
        assert a == b

    def test_empty_pack(self):
        d = ContextPack(budget=50).to_dict()
        assert d["items"] == []
        assert d["headroom"] == 50


class TestContextCliJson:
    def test_json_output_parses(self, capsys):
        rc = main(["context", "--seed", "5", "--days", "7", "--budget", "300", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["within_budget"] is True
        assert payload["total_tokens"] <= payload["budget"]
        assert isinstance(payload["items"], list)

    def test_text_mode_unchanged(self, capsys):
        rc = main(["context", "--seed", "5", "--days", "7"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "=== Context Pack" in out
        assert "Within budget: True" in out
