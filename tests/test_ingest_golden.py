"""Golden fixture pinning episode segmentation output.

``fixtures/ingest_episodes_golden.json`` is the canonical serialization of
the episodes produced for a fixed synthetic event set. Any change to
segmentation or episode serialization makes this test fail, so drift is
always deliberate: regenerate the fixture only together with the change
that justifies it.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mnemofold.events import Event
from mnemofold.ingest import EpisodeSegmenter

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "ingest_episodes_golden.json"

T0 = datetime(2025, 3, 10, 9, 0, tzinfo=UTC)


def golden_events() -> list[Event]:
    """Fixed input events for the golden segmentation fixture."""
    return [
        Event.mail_received(
            T0, sender="alice", subject="kickoff", recipients=["bob"], thread_id="t1"
        ),
        Event.mail_received(
            T0 + timedelta(minutes=20),
            sender="bob",
            subject="kickoff",
            body="sounds good",
            recipients=["alice"],
            thread_id="t1",
        ),
        Event.note(T0 + timedelta(minutes=40), text="write design doc", author="alice"),
        Event.mail_received(
            T0 + timedelta(hours=3),
            sender="carol",
            subject="budget",
            recipients=["alice"],
            thread_id="t2",
        ),
        Event.document_change(
            T0 + timedelta(hours=3, minutes=10),
            doc_id="doc-alpha-7",
            title="plan",
            change_type="edit",
            author="bob",
        ),
        Event.task_update(
            T0 + timedelta(hours=4),
            task_id="tk-1",
            title="draft spec",
            status="in_progress",
            owner="alice",
        ),
        Event.focus_block(T0 + timedelta(days=1), duration_minutes=90, topic="deep work"),
        Event.chat_message(
            T0 + timedelta(days=1, minutes=95),
            sender="bob",
            body="lgtm",
            channel="eng",
            thread_id="chat1",
        ),
    ]


def golden_payload() -> str:
    """Canonical JSON text the fixture file must match byte-for-byte."""
    episodes = EpisodeSegmenter().segment(golden_events())
    return json.dumps([episode.to_dict() for episode in episodes], indent=2, sort_keys=True) + "\n"


class TestGoldenEpisodes:
    def test_segmentation_matches_golden_fixture(self):
        assert GOLDEN_PATH.exists(), "golden fixture missing; regenerate it deliberately"
        assert golden_payload() == GOLDEN_PATH.read_text()

    def test_golden_regeneration_is_stable(self):
        assert golden_payload() == golden_payload()

    def test_fixture_exercises_thread_gap_and_group_splits(self):
        episodes = EpisodeSegmenter().segment(golden_events())
        # [t1 mail, t1 reply, note] / [t2 mail, doc change, task update]
        # / [focus block] / [chat message]
        assert [len(episode.events) for episode in episodes] == [3, 3, 1, 1]
        assert "thread:t1" in episodes[0].tags
        assert "thread:chat1" in episodes[3].tags
