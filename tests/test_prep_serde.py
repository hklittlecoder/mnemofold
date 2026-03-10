"""Meeting prep packet serialization roundtrips."""

from mnemofold.prep import MeetingPrep, PrepItem


def make_packet() -> MeetingPrep:
    return MeetingPrep(
        meeting_id="m1",
        meeting_title="Release sync",
        attendee_names=["ana", "bo"],
        agenda_items=["Review open commitments (1) - cites mem-1"],
        items=[
            PrepItem(
                item_id="mem-1",
                title="Release checklist",
                category="commitment",
                summary="Ship by Friday",
                citation="[mem-1]",
                priority=0.75,
            )
        ],
        total_items=1,
        cited_sources=["mem-1"],
    )


class TestPrepSerde:
    def test_roundtrip_preserves_packet(self):
        packet = make_packet()
        assert MeetingPrep.from_dict(packet.to_dict()) == packet

    def test_priority_quantized(self):
        item = PrepItem(
            item_id="x",
            title="t",
            category="note",
            summary="s",
            citation="[x]",
            priority=0.1234567891,
        )
        assert item.to_dict()["priority"] == 0.123457

    def test_empty_packet_roundtrip(self):
        packet = MeetingPrep(meeting_id="m0", meeting_title="empty")
        assert MeetingPrep.from_dict(packet.to_dict()) == packet
        assert packet.to_dict()["total_items"] == 0

    def test_to_dict_is_deterministic(self):
        assert make_packet().to_dict() == make_packet().to_dict()

    def test_from_dict_tolerates_missing_optionals(self):
        packet = MeetingPrep.from_dict({"meeting_id": "m2"})
        assert packet.meeting_title == ""
        assert packet.items == []
        assert packet.total_items == 0
