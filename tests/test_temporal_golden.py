"""Golden fixture pinning as-of query answers.

``fixtures/temporal_asof_golden.json`` records the answers a fixed fact
history gives at fixed probe instants, including probes that sit between
two versions whose bounds are written with different UTC offsets. Any
change to interval semantics makes this fixture mismatch, so drift in the
as-of engine is always deliberate.
"""

import json
from pathlib import Path

from mnemofold.temporal import IntervalFact, TemporalStore

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "temporal_asof_golden.json"

PROBES = (
    "2025-01-01T00:00:00+00:00",
    "2025-02-10T09:30:00+00:00",
    "2025-02-10T10:30:00+00:00",
    "2025-03-15T12:00:00+00:00",
    "2025-06-01T00:00:00+00:00",
)


def golden_store() -> TemporalStore[str]:
    """Fixed fact history mixing +08:00 and +00:00 bounds."""
    store: TemporalStore[str] = TemporalStore()
    store.add(
        IntervalFact(
            "project:alpha:owner",
            "alice",
            "2025-01-06T09:00:00+08:00",
            "2025-02-10T18:00:00+08:00",  # == 10:00Z
        )
    )
    store.add(
        IntervalFact(
            "project:alpha:owner",
            "bob",
            "2025-02-10T10:00:00+00:00",
            "2025-04-01T00:00:00+00:00",
        )
    )
    store.add(IntervalFact("project:alpha:owner", "carol", "2025-04-01T00:00:00+00:00"))
    store.add(
        IntervalFact(
            "project:alpha:status",
            "planning",
            "2025-01-06T00:00:00+00:00",
            "2025-03-01T00:00:00+00:00",
        )
    )
    store.add(IntervalFact("project:alpha:status", "building", "2025-03-01T00:00:00+00:00"))
    return store


def golden_payload() -> str:
    store = golden_store()
    keys = store.keys()
    probes: dict[str, dict[str, str | None]] = {}
    for probe in PROBES:
        answers: dict[str, str | None] = {}
        for key in keys:
            fact = store.as_of(key, probe)
            answers[key] = fact.value if fact is not None else None
        probes[probe] = answers
    current: dict[str, str | None] = {}
    for key in keys:
        fact = store.current(key)
        current[key] = fact.value if fact is not None else None
    payload = {
        "probes": probes,
        "current": current,
        "history_lengths": {key: len(store.history(key)) for key in keys},
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class TestGoldenAsOf:
    def test_answers_match_golden_fixture(self):
        assert GOLDEN_PATH.exists(), "golden fixture missing; regenerate it deliberately"
        assert golden_payload() == GOLDEN_PATH.read_text()

    def test_regeneration_is_stable(self):
        assert golden_payload() == golden_payload()

    def test_offset_probe_documented_directly(self):
        # 09:30Z is before alice's 10:00Z end; 10:30Z is inside bob's term.
        store = golden_store()
        early = store.as_of("project:alpha:owner", "2025-02-10T09:30:00+00:00")
        late = store.as_of("project:alpha:owner", "2025-02-10T10:30:00+00:00")
        assert early is not None and early.value == "alice"
        assert late is not None and late.value == "bob"
