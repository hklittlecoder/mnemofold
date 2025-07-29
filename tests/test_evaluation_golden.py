"""Golden fixture pinning the evaluation suite's measured output.

``fixtures/evaluation_suite_golden.json`` records every scenario card's
metric values and the aggregate for a fixed synthetic configuration
(seed 42, 60 days). All numbers are measurements on planted ground
truth; regenerating this file is how deliberate metric drift is
reviewed. Nothing here is a real-corpus or real-user result.
"""

import json
from pathlib import Path

from mnemofold.evaluation import ScenarioConfig, run_suite

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "evaluation_suite_golden.json"


def golden_payload() -> str:
    suite = run_suite(ScenarioConfig(seed=42, days=60))
    payload = {
        "cards": [
            {
                "scenario": card.scenario,
                "overall_pass": card.overall_pass(),
                "metrics": {m.name: m.value for m in card.metrics},
            }
            for card in suite.cards
        ],
        "aggregate": {m.name: m.value for m in suite.aggregate.metrics},
        "overall_pass": suite.overall_pass(),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class TestGoldenSuite:
    def test_suite_matches_golden_fixture(self):
        assert GOLDEN_PATH.exists(), "golden fixture missing; regenerate it deliberately"
        assert golden_payload() == GOLDEN_PATH.read_text()

    def test_regeneration_is_stable(self):
        assert golden_payload() == golden_payload()
