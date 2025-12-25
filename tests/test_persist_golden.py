"""Golden guard: canonical envelope bytes must not drift.

The fixture is byte-compared against freshly produced envelope text, so
any change to key order, separators or the schema-version field fails
here deliberately rather than silently altering persisted artifacts.
"""

from pathlib import Path

from mnemofold.persist import dump_envelope, parse_envelope

FIXTURE = Path(__file__).parent / "fixtures" / "persist_envelope_golden.json"


def _payload() -> dict:
    return {"params": [1.5, 0.75], "docs": {"d2": "beta gamma", "d1": "alpha beta"}}


def test_dump_matches_golden_bytes():
    assert dump_envelope("golden_demo", _payload()) == FIXTURE.read_text(encoding="utf-8")


def test_golden_parses_back_to_payload():
    text = FIXTURE.read_text(encoding="utf-8")
    assert parse_envelope(text, "golden_demo") == _payload()


def test_golden_regeneration_is_stable():
    first = dump_envelope("golden_demo", _payload())
    second = dump_envelope("golden_demo", _payload())
    assert first == second == FIXTURE.read_text(encoding="utf-8")
