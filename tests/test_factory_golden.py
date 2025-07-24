"""Golden fixture pinning a small factory history end to end.

``fixtures/factory_history_golden.json`` captures the manifest, event
type distribution, boundary events, and checksum for a fixed seed and
day count. Any change to generation order, rng consumption, payload
shape, or the checksum algorithm makes this test fail, so drift in the
synthetic corpus is always deliberate and reviewed.
"""

import json
from pathlib import Path

from mnemofold.factory import WorkHistoryFactory

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "factory_history_golden.json"


def golden_payload() -> str:
    factory = WorkHistoryFactory(seed=7, days=14)
    events, manifest = factory.generate()
    type_counts: dict[str, int] = {}
    for event in events:
        type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1
    payload = {
        "seed": manifest.seed,
        "days": manifest.days,
        "event_count": manifest.event_count,
        "checksum": manifest.checksum,
        "personas": manifest.personas,
        "projects": manifest.projects,
        "planted": {
            "commitments": manifest.planted_commitments,
            "decisions": manifest.planted_decisions,
            "contradictions": manifest.planted_contradictions,
        },
        "event_type_counts": type_counts,
        "first_event": {
            "id": events[0].event_id,
            "type": events[0].event_type,
            "timestamp": events[0].timestamp,
        },
        "last_event": {
            "id": events[-1].event_id,
            "type": events[-1].event_type,
            "timestamp": events[-1].timestamp,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class TestFactoryGolden:
    def test_history_matches_golden_fixture(self):
        assert GOLDEN_PATH.exists(), "golden fixture missing; regenerate it deliberately"
        assert golden_payload() == GOLDEN_PATH.read_text()

    def test_regeneration_is_stable(self):
        assert golden_payload() == golden_payload()
