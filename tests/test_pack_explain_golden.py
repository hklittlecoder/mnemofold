"""Golden bytes for explain_pack on a hand-computed knapsack instance.

A(10 tok, 3.0) + B(10 tok, 2.0) beat C(15 tok, 4.0) under a budget of
20 tokens: total value 5.0 vs 4.0. The frozen payload pins the row
order, densities, and the outcompeted verdict for C.
"""

import json
from pathlib import Path

from mnemofold.canon import canonical_json
from mnemofold.context import ContextItem, ContextPacker, explain_pack

FIXTURE = Path(__file__).parent / "fixtures" / "pack_explain_golden.json"


def instance():
    items = [
        ContextItem(item_id="A", content="a", token_estimate=10, priority=3.0),
        ContextItem(item_id="B", content="b", token_estimate=10, priority=2.0),
        ContextItem(item_id="C", content="c", token_estimate=15, priority=4.0),
    ]
    return ContextPacker(budget=20), items


class TestExplainGolden:
    def test_matches_golden_bytes(self):
        packer, items = instance()
        assert canonical_json(explain_pack(packer, items)) == FIXTURE.read_text(encoding="utf-8")

    def test_golden_selection_is_optimal(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        selected = {row["item_id"] for row in payload["rows"] if row["selected"]}
        assert selected == {"A", "B"}
        assert payload["used"] == 20
        assert payload["headroom"] == 0

    def test_regeneration_is_stable(self):
        packer, items = instance()
        assert explain_pack(packer, items) == explain_pack(packer, items)
