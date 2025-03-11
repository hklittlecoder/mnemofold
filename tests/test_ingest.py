"""Tests for ingestion: episode segmentation and entity resolution."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event
from mnemofold.ingest import AliasTable, Entity, EpisodeSegmenter

T0 = datetime(2025, 3, 10, 9, 0, tzinfo=UTC)


def _mail(ts: datetime, thread: str, subject: str = "sync") -> Event:
    return Event.mail_received(
        ts, sender="alice", subject=subject, recipients=["bob"], thread_id=thread
    )


class TestEpisodeSegmenterBasics:
    def test_empty_input_yields_no_episodes(self):
        assert EpisodeSegmenter().segment([]) == []

    def test_single_event_forms_one_episode(self):
        episodes = EpisodeSegmenter().segment([_mail(T0, "t1")])
        assert len(episodes) == 1
        assert len(episodes[0].events) == 1
        assert episodes[0].start_time == T0
        assert episodes[0].end_time == T0

    def test_same_thread_close_events_group_together(self):
        events = [_mail(T0, "t1"), _mail(T0 + timedelta(minutes=10), "t1")]
        episodes = EpisodeSegmenter().segment(events)
        assert len(episodes) == 1
        assert len(episodes[0].events) == 2

    def test_different_threads_split_into_separate_episodes(self):
        events = [
            _mail(T0, "t1"),
            _mail(T0 + timedelta(minutes=5), "t2"),
            _mail(T0 + timedelta(minutes=10), "t1"),
        ]
        episodes = EpisodeSegmenter().segment(events)
        assert len(episodes) == 3

    def test_gap_larger_than_threshold_starts_new_episode(self):
        events = [_mail(T0, "t1"), _mail(T0 + timedelta(minutes=61), "t1")]
        episodes = EpisodeSegmenter(gap_minutes=60).segment(events)
        assert len(episodes) == 2

    def test_gap_exactly_at_threshold_stays_in_episode(self):
        events = [_mail(T0, "t1"), _mail(T0 + timedelta(minutes=60), "t1")]
        episodes = EpisodeSegmenter(gap_minutes=60).segment(events)
        assert len(episodes) == 1

    def test_episode_ids_are_deterministic(self):
        events = [_mail(T0, "t1"), _mail(T0 + timedelta(minutes=5), "t1")]
        first = EpisodeSegmenter().segment(events)
        second = EpisodeSegmenter().segment(events)
        assert [e.episode_id for e in first] == [e.episode_id for e in second]
        assert first[0].episode_id.startswith("ep_")

    def test_participants_extracted_from_mail(self):
        events = [_mail(T0, "t1")]
        episodes = EpisodeSegmenter().segment(events)
        assert episodes[0].participants == {"alice", "bob"}

    def test_group_key_recorded_as_tag(self):
        events = [_mail(T0, "t1"), _mail(T0 + timedelta(minutes=5), "t1")]
        episodes = EpisodeSegmenter().segment(events)
        assert "thread:t1" in episodes[0].tags


class TestAliasTableBasics:
    def _table(self) -> AliasTable:
        table = AliasTable()
        table.add_entity(
            Entity(
                entity_id="p1",
                entity_type="person",
                name="Alice Zhang",
                aliases=["alice", "azhang"],
            )
        )
        return table

    def test_resolve_canonical_name_and_aliases(self):
        table = self._table()
        assert table.resolve("Alice Zhang") == "p1"
        assert table.resolve("ALICE") == "p1"
        assert table.resolve("azhang") == "p1"

    def test_resolve_unknown_returns_none(self):
        assert self._table().resolve("nobody") is None

    def test_get_entity_roundtrip(self):
        table = self._table()
        entity = table.get("p1")
        assert entity is not None
        assert entity.name == "Alice Zhang"
        assert table.get("missing") is None
