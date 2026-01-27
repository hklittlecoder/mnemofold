"""Strict thread/meeting segmentation modes and their boundaries."""

from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.events import Event, EventType
from mnemofold.ingest import SEGMENT_MODES, EpisodeSegmenter, SegmentConfig

T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def ev(when, *, thread=None, meeting=None, subject="s", etype=EventType.MAIL_RECEIVED):
    content: dict = {"subject": subject}
    if thread is not None:
        content["thread_id"] = thread
    if meeting is not None:
        content["meeting_id"] = meeting
    return Event(event_type=etype, timestamp=when, content=content)


class TestThreadMode:
    def test_same_thread_stays_together_across_large_gaps(self):
        events = [ev(T0, thread="t1"), ev(T0 + timedelta(hours=9), thread="t1")]
        eps = EpisodeSegmenter(mode="thread").segment(events)
        assert len(eps) == 1
        assert len(eps[0].events) == 2
        assert "thread:t1" in eps[0].tags

    def test_interleaved_threads_split(self):
        events = [
            ev(T0, thread="t1"),
            ev(T0 + timedelta(minutes=5), thread="t2"),
            ev(T0 + timedelta(minutes=10), thread="t1"),
        ]
        eps = EpisodeSegmenter(mode="thread").segment(events)
        assert len(eps) == 2
        by_tag = {next(t for t in e.tags if t.startswith("thread:")): e for e in eps}
        assert len(by_tag["thread:t1"].events) == 2
        assert len(by_tag["thread:t2"].events) == 1

    def test_keyless_events_fall_back_to_gap(self):
        events = [ev(T0), ev(T0 + timedelta(minutes=10)), ev(T0 + timedelta(hours=6))]
        eps = EpisodeSegmenter(mode="thread").segment(events)
        assert len(eps) == 2

    def test_keyless_fallback_ignores_the_other_key_kind(self):
        # in thread mode, meeting ids must not regroup keyless events
        events = [
            ev(T0, meeting="m1"),
            ev(T0 + timedelta(minutes=5), meeting="m1"),
            ev(T0 + timedelta(hours=6)),
        ]
        eps = EpisodeSegmenter(mode="thread").segment(events)
        assert len(eps) == 2

    def test_cap_splits_large_thread(self):
        events = [ev(T0 + timedelta(minutes=i), thread="t1") for i in range(5)]
        eps = EpisodeSegmenter(mode="thread", max_episode_events=2).segment(events)
        assert [len(e.events) for e in eps] == [2, 2, 1]

    def test_thread_mode_merges_what_gap_mode_splits(self):
        events = [ev(T0, thread="t1"), ev(T0 + timedelta(hours=3), thread="t1")]
        assert len(EpisodeSegmenter(mode="gap").segment(events)) == 2
        assert len(EpisodeSegmenter(mode="thread").segment(events)) == 1

    def test_episode_bounds_span_the_thread(self):
        events = [ev(T0, thread="t1"), ev(T0 + timedelta(hours=3), thread="t1")]
        ep = EpisodeSegmenter(mode="thread").segment(events)[0]
        assert ep.start_time == T0
        assert ep.end_time == T0 + timedelta(hours=3)

    def test_titles_come_from_the_first_event(self):
        events = [ev(T0, thread="t1", subject="Release plan")]
        eps = EpisodeSegmenter(mode="thread").segment(events)
        assert eps[0].title == "Release plan"


class TestMeetingMode:
    def test_meetings_group_by_meeting_id(self):
        events = [
            ev(T0, meeting="m1", etype=EventType.MEETING_HELD),
            ev(T0 + timedelta(hours=8), meeting="m1", etype=EventType.MEETING_HELD),
            ev(T0 + timedelta(minutes=30), meeting="m2", etype=EventType.MEETING_HELD),
        ]
        eps = EpisodeSegmenter(mode="meeting").segment(events)
        assert len(eps) == 2
        assert any("meeting:m1" in e.tags and len(e.events) == 2 for e in eps)

    def test_thread_ids_do_not_group_in_meeting_mode(self):
        events = [ev(T0, thread="t1"), ev(T0 + timedelta(hours=5), thread="t1")]
        eps = EpisodeSegmenter(mode="meeting").segment(events)
        assert len(eps) == 2  # gap fallback splits them (5h > 60min)


class TestModeValidationAndOrder:
    def test_known_modes(self):
        assert sorted(SEGMENT_MODES) == ["day", "gap", "meeting", "thread"]

    @pytest.mark.parametrize("mode", ["thread", "meeting"])
    def test_config_accepts_new_modes(self, mode):
        cfg = SegmentConfig(mode=mode)
        assert EpisodeSegmenter.from_config(cfg).mode == mode

    def test_unknown_mode_rejected_everywhere(self):
        with pytest.raises(ValueError, match="unknown segmentation mode"):
            SegmentConfig(mode="weekly")
        with pytest.raises(ValueError, match="unknown segmentation mode"):
            EpisodeSegmenter(mode="weekly")

    def test_config_roundtrip_preserves_mode(self):
        cfg = SegmentConfig(mode="thread", gap_minutes=30)
        assert SegmentConfig.from_dict(cfg.to_dict()) == cfg

    def test_output_sorted_by_start_time(self):
        events = [
            ev(T0 + timedelta(hours=5), thread="late"),
            ev(T0),
            ev(T0 + timedelta(minutes=10), thread="mid"),
        ]
        eps = EpisodeSegmenter(mode="thread").segment(events)
        starts = [e.start_time for e in eps]
        assert starts == sorted(starts)

    def test_day_mode_still_works(self):
        events = [ev(T0, thread="t1"), ev(T0 + timedelta(days=1), thread="t1")]
        eps = EpisodeSegmenter(mode="day", day_tz="UTC").segment(events)
        assert len(eps) == 2
        assert any("day:2026-03-02" in e.tags for e in eps)

    def test_mixed_input_double_run_identical(self):
        events = [ev(T0 + timedelta(minutes=7 * i), thread=f"t{i % 3}") for i in range(6)]
        events.append(ev(T0 + timedelta(hours=4)))
        a = EpisodeSegmenter(mode="thread", max_episode_events=2).segment(events)
        b = EpisodeSegmenter(mode="thread", max_episode_events=2).segment(events)
        assert [(e.episode_id, len(e.events)) for e in a] == [
            (e.episode_id, len(e.events)) for e in b
        ]

    def test_empty_input(self):
        assert EpisodeSegmenter(mode="thread").segment([]) == []
