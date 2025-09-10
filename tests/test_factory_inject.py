"""Tests for injecting custom events into seeded synthetic histories."""

from __future__ import annotations

import json

from mnemofold.factory import SyntheticEvent, WorkHistoryFactory


def _factory() -> WorkHistoryFactory:
    return WorkHistoryFactory(seed=11, days=5)


def _fingerprint(events: list[SyntheticEvent]) -> list[tuple[str, str, str]]:
    return [
        (e.timestamp, e.event_type, json.dumps(e.payload, sort_keys=True, default=str))
        for e in events
    ]


class TestEventInjection:
    def test_injected_event_joins_the_timeline(self):
        factory = _factory()
        factory.inject_event("note", "2025-01-02T14:30:00+00:00", {"text": "manual audit note"})
        events, manifest = factory.generate()
        matches = [e for e in events if e.payload.get("text") == "manual audit note"]
        assert len(matches) == 1
        assert manifest.event_count == len(events)

    def test_seeded_stream_is_undisturbed(self):
        baseline, _ = _factory().generate()
        factory = _factory()
        factory.inject_event(
            "chat_message", "2025-01-03T09:15:00+00:00", {"text": "injected ping", "sender": "ops"}
        )
        injected, _ = factory.generate()
        seeded = [e for e in injected if e.payload.get("text") != "injected ping"]
        assert _fingerprint(seeded) == _fingerprint(baseline)
        assert len(injected) == len(baseline) + 1

    def test_injection_keeps_the_timeline_sorted(self):
        factory = _factory()
        factory.inject_event("note", "2025-01-02T23:59:00+00:00", {"text": "late note"})
        events, _ = factory.generate()
        stamps = [e.timestamp for e in events]
        assert stamps == sorted(stamps)

    def test_regeneration_with_injections_is_deterministic(self):
        factory = _factory()
        factory.inject_event("note", "2025-01-02T08:00:00+00:00", {"text": "repeatable"})
        _, first = factory.generate()
        _, second = factory.generate()
        assert first.checksum == second.checksum
        assert first.event_count == second.event_count

    def test_checksum_differs_from_uninjected_history(self):
        _, plain = _factory().generate()
        factory = _factory()
        factory.inject_event("note", "2025-01-02T08:00:00+00:00", {"text": "changes checksum"})
        _, injected = factory.generate()
        assert plain.checksum != injected.checksum

    def test_injected_ids_are_woven_into_sequential_numbering(self):
        factory = _factory()
        factory.inject_event("note", "2025-01-01T12:00:00+00:00", {"text": "midday"})
        events, _ = factory.generate()
        ids = [e.event_id for e in events]
        assert ids == [f"evt-{i:06d}" for i in range(len(events))]
