"""Ingestion pipeline: segment events into episodes and extract entities.

The ingestion pipeline turns raw work events into structured episodic
memory with extracted entities, commitments, decisions, and document
references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from mnemofold.events import Event, EventType


@dataclass(slots=True)
class Episode:
    """A coherent group of events forming one episode.

    Episodes are segments of related events (e.g. an email thread,
    a meeting, a day of focused work on a project).
    """

    episode_id: str
    title: str
    start_time: datetime
    end_time: datetime
    events: list[Event] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    participants: set[str] = field(default_factory=set)

    def add_event(self, event: Event) -> None:
        self.events.append(event)
        # Update time bounds
        if event.timestamp < self.start_time:
            self.start_time = event.timestamp
        if event.timestamp > self.end_time:
            self.end_time = event.timestamp
        # Extract participants
        self._extract_participants(event)

    def _extract_participants(self, event: Event) -> None:
        d = event.content
        if "sender" in d:
            self.participants.add(d["sender"])
        for r in d.get("recipients", []):
            self.participants.add(r)
        for a in d.get("attendees", []):
            self.participants.add(a)
        if "assignee" in d:
            self.participants.add(d["assignee"])
        if "author" in d:
            self.participants.add(d["author"])


@dataclass(slots=True)
class Entity:
    """An entity resolved from events."""

    entity_id: str
    entity_type: str  # person, project, org, etc.
    name: str
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AliasTable:
    """Maps aliases to canonical entity IDs.

    Supports fuzzy alias resolution and merge candidate detection.
    """

    _aliases: dict[str, str] = field(default_factory=dict)  # alias -> entity_id
    _entities: dict[str, Entity] = field(default_factory=dict)

    def add_entity(self, entity: Entity) -> None:
        """Register an entity with its name and aliases."""
        self._entities[entity.entity_id] = entity
        self._aliases[entity.name.lower()] = entity.entity_id
        for alias in entity.aliases:
            self._aliases[alias.lower()] = entity.entity_id

    def resolve(self, name: str) -> str | None:
        """Resolve a name to an entity ID. Returns None if not found."""
        return self._aliases.get(name.lower())

    def get(self, entity_id: str) -> Entity | None:
        """Get an entity by ID."""
        return self._entities.get(entity_id)

    def all_entities(self) -> list[Entity]:
        """Return all registered entities."""
        return list(self._entities.values())

    def merge_candidates(self, threshold: float = 0.8) -> list[tuple[str, str, float]]:
        """Find pairs of entities that might be the same.

        Uses simple string similarity on names as a heuristic.
        Returns list of (id1, id2, similarity) tuples.
        """
        candidates: list[tuple[str, str, float]] = []
        ids = sorted(self._entities.keys())
        for i, id1 in enumerate(ids):
            n1 = self._entities[id1].name.lower()
            for id2 in ids[i + 1 :]:
                n2 = self._entities[id2].name.lower()
                sim = _name_similarity(n1, n2)
                if sim >= threshold:
                    candidates.append((id1, id2, sim))
        return candidates


def _name_similarity(a: str, b: str) -> float:
    """Compute a simple name similarity score (0.0 to 1.0).

    Based on the Jaccard similarity of character bigrams.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    def bigrams(s: str) -> set[str]:
        return {s[i : i + 2] for i in range(len(s) - 1)}

    bg_a = bigrams(a)
    bg_b = bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    intersection = len(bg_a & bg_b)
    union = len(bg_a | bg_b)
    return intersection / union if union else 0.0


@dataclass
class EpisodeSegmenter:
    """Segments events into episodes using configurable gap rules.

    Events within ``gap_minutes`` of each other in the same thread/meeting
    are grouped into one episode. Events with different thread/meeting IDs
    form separate episodes even if close in time.
    """

    gap_minutes: int = 60
    group_by_thread: bool = True
    group_by_meeting: bool = True

    def segment(self, events: list[Event]) -> list[Episode]:
        """Segment a list of events into episodes.

        Events should be sorted by timestamp (oldest first).
        """
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        episodes: list[Episode] = []
        current_episode: Episode | None = None
        current_group: str | None = None
        last_time: datetime | None = None

        for event in sorted_events:
            group_key = self._group_key(event)

            if current_episode is None:
                current_episode = self._start_episode(event)
                episodes.append(current_episode)
            elif (group_key is not None and group_key != current_group) or self._gap_exceeds(
                last_time, event.timestamp
            ):
                # Different thread/meeting or gap too large -> new episode
                current_episode = self._start_episode(event)
                episodes.append(current_episode)
            else:
                current_episode.add_event(event)

            if group_key is not None:
                current_group = group_key
                current_episode.tags.add(group_key)

            last_time = event.timestamp

        return episodes

    def _group_key(self, event: Event) -> str | None:
        d = event.content
        if self.group_by_thread and "thread_id" in d:
            return "thread:" + d["thread_id"]
        if self.group_by_meeting and "meeting_id" in d:
            return "meeting:" + d["meeting_id"]
        return None

    def _start_episode(self, event: Event) -> Episode:
        eid = "ep_" + event.event_id[:12]
        title = self._derive_title(event)
        ep = Episode(
            episode_id=eid,
            title=title,
            start_time=event.timestamp,
            end_time=event.timestamp,
        )
        ep.add_event(event)
        return ep

    def _derive_title(self, event: Event) -> str:
        d = event.content
        if "subject" in d:
            return d["subject"]
        if "title" in d:
            return d["title"]
        if event.event_type == EventType.FOCUS_BLOCK:
            return f"Focus: {d.get('activity', 'work')}"
        return str(event.event_type)

    def _gap_exceeds(self, t1: datetime | None, t2: datetime) -> bool:
        if t1 is None:
            return False
        dt1 = t1 if t1.tzinfo is not None else t1.replace(tzinfo=UTC)
        dt2 = t2 if t2.tzinfo is not None else t2.replace(tzinfo=UTC)
        return (dt2 - dt1) > timedelta(minutes=self.gap_minutes)
