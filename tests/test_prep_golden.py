"""Golden fixture for the serialized meeting prep packet."""

import json
from pathlib import Path

from mnemofold.canon import canonical_json
from mnemofold.prep import MeetingPrep, PrepItem

FIXTURE = Path(__file__).parent / "fixtures" / "prep_packet_golden.json"


def make_packet() -> MeetingPrep:
    return MeetingPrep(
        meeting_id="m-sync",
        meeting_title="Release sync",
        attendee_names=["ana", "bo"],
        agenda_items=[
            "Review open commitments (1) - cites mem-1",
            "Open discussion",
            "Action items",
        ],
        items=[
            PrepItem(
                item_id="mem-1",
                title="Release checklist",
                category="commitment",
                summary="Ship the release checklist by Friday",
                citation="[mem-1]",
                priority=0.75,
            )
        ],
        total_items=1,
        cited_sources=["mem-1"],
    )


def test_packet_matches_golden_bytes():
    assert canonical_json(make_packet().to_dict()) == FIXTURE.read_text(encoding="utf-8")


def test_golden_loads_to_equal_packet():
    loaded = MeetingPrep.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert loaded == make_packet()


def test_regeneration_is_stable():
    first = canonical_json(make_packet().to_dict())
    second = canonical_json(make_packet().to_dict())
    assert first == second == FIXTURE.read_text(encoding="utf-8")
