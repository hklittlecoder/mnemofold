"""Ingestion pipeline: segment events into episodes and extract entities.

The ingestion pipeline turns raw work events into structured episodic
memory with extracted entities, commitments, decisions, and document
references.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from mnemofold.events import Event, EventType
from mnemofold.textsim import bigram_jaccard


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

    def to_dict(self) -> dict[str, Any]:
        """Serialize deterministically; events become verified envelopes.

        Tags and participants are sorted so equivalent episodes produce
        byte-identical JSON regardless of insertion order.
        """
        return {
            "episode_id": self.episode_id,
            "title": self.title,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "events": [event.to_envelope() for event in self.events],
            "tags": sorted(self.tags),
            "participants": sorted(self.participants),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Episode:
        """Rebuild an episode, re-verifying every embedded event envelope."""
        episode = cls(
            episode_id=data["episode_id"],
            title=data["title"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            tags=set(data.get("tags", ())),
            participants=set(data.get("participants", ())),
        )
        for envelope in data.get("events", ()):
            episode.events.append(Event.from_envelope(envelope))
        return episode

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


@dataclass(frozen=True, slots=True)
class MergeRecord:
    """Provenance for one entity merge: what moved and why."""

    source_id: str
    target_id: str
    reason: str
    aliases_moved: tuple[str, ...]


@dataclass(slots=True)
class AliasTable:
    """Maps aliases to canonical entity IDs.

    Supports fuzzy alias resolution and merge candidate detection.
    """

    _aliases: dict[str, str] = field(default_factory=dict)  # alias -> entity_id
    _entities: dict[str, Entity] = field(default_factory=dict)
    _merged: dict[str, str] = field(default_factory=dict)  # source_id -> target_id
    _history: list[MergeRecord] = field(default_factory=list)

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

    def merged_into(self, entity_id: str) -> str | None:
        """Final target of a retired entity id, following merge chains.

        Returns None when the id was never merged away.
        """
        seen: set[str] = set()
        current = entity_id
        while current in self._merged and current not in seen:
            seen.add(current)
            current = self._merged[current]
        return current if current != entity_id else None

    def merge(self, source_id: str, target_id: str, reason: str = "") -> MergeRecord:
        """Fold the source entity into the target and record the merge.

        Every alias of the source (including its canonical name) starts
        resolving to the target; the source entity itself retires, but its
        id keeps redirecting through ``merged_into`` so resolution stays
        auditable in both directions.
        """
        if source_id == target_id:
            raise ValueError("cannot merge an entity into itself")
        source = self._entities.get(source_id)
        if source is None:
            raise ValueError(f"unknown source entity: {source_id}")
        if self._entities.get(target_id) is None:
            raise ValueError(f"unknown target entity: {target_id}")
        moved: set[str] = set()
        for alias, owner in list(self._aliases.items()):
            if owner == source_id:
                self._aliases[alias] = target_id
                moved.add(alias)
        for alias in source.aliases:
            key = alias.lower()
            if key not in self._aliases:
                self._aliases[key] = target_id
                moved.add(key)
        name_key = source.name.lower()
        if name_key not in self._aliases:
            self._aliases[name_key] = target_id
            moved.add(name_key)
        del self._entities[source_id]
        self._merged[source_id] = target_id
        record = MergeRecord(
            source_id=source_id,
            target_id=target_id,
            reason=reason,
            aliases_moved=tuple(sorted(moved)),
        )
        self._history.append(record)
        return record

    def merge_history(self) -> list[MergeRecord]:
        """All merges applied so far, in application order."""
        return list(self._history)


def _name_similarity(a: str, b: str) -> float:
    """Case-sensitive name similarity score (0.0 to 1.0).

    Character-bigram Jaccard via the shared primitive — the same
    measure folding uses for near-duplicates, but names keep their
    case so differently-cased candidates stay distinguishable.
    """
    return bigram_jaccard(a, b)


SEGMENT_MODES = ("gap", "day", "thread", "meeting")


@dataclass(frozen=True, slots=True)
class SegmentConfig:
    """Declarative, serializable rules for episode segmentation.

    ``max_episode_events`` bounds episode size (0 means unbounded);
    oversized episodes are split even when the gap rule would keep them
    together, so downstream context packing sees predictable granularity.
    """

    gap_minutes: int = 60
    max_episode_events: int = 0
    group_by_thread: bool = True
    group_by_meeting: bool = True
    mode: str = "gap"
    day_tz: str = "UTC"

    def __post_init__(self) -> None:
        if self.mode not in SEGMENT_MODES:
            raise ValueError(f"unknown segmentation mode: {self.mode}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_minutes": self.gap_minutes,
            "max_episode_events": self.max_episode_events,
            "group_by_thread": self.group_by_thread,
            "group_by_meeting": self.group_by_meeting,
            "mode": self.mode,
            "day_tz": self.day_tz,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SegmentConfig:
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown segment config keys: {unknown}")
        return cls(**{k: v for k, v in data.items() if k in known})


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
    max_episode_events: int = 0
    mode: str = "gap"
    day_tz: str = "UTC"

    def __post_init__(self) -> None:
        if self.mode not in SEGMENT_MODES:
            raise ValueError(f"unknown segmentation mode: {self.mode}")

    @classmethod
    def from_config(cls, config: SegmentConfig) -> EpisodeSegmenter:
        """Build a segmenter from a declarative config."""
        return cls(
            gap_minutes=config.gap_minutes,
            group_by_thread=config.group_by_thread,
            group_by_meeting=config.group_by_meeting,
            max_episode_events=config.max_episode_events,
            mode=config.mode,
            day_tz=config.day_tz,
        )

    def segment(self, events: list[Event]) -> list[Episode]:
        """Segment a list of events into episodes.

        Events should be sorted by timestamp (oldest first).
        """
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        if self.mode == "day":
            return self._segment_by_day(sorted_events)
        if self.mode in ("thread", "meeting"):
            return self._segment_by_key(sorted_events, self.mode)
        return self._segment_gap(sorted_events)

    def _segment_gap(self, sorted_events: list[Event]) -> list[Episode]:
        """Gap-rule segmentation: the default ``gap`` mode."""
        episodes: list[Episode] = []
        current_episode: Episode | None = None
        current_group: str | None = None
        last_time: datetime | None = None

        for event in sorted_events:
            group_key = self._group_key(event)

            if current_episode is None:
                current_episode = self._start_episode(event)
                episodes.append(current_episode)
            elif (
                (group_key is not None and group_key != current_group)
                or self._gap_exceeds(last_time, event.timestamp)
                or self._is_full(current_episode)
            ):
                # Different thread/meeting, gap too large, or size cap -> new episode
                current_episode = self._start_episode(event)
                episodes.append(current_episode)
            else:
                current_episode.add_event(event)

            if group_key is not None:
                current_group = group_key
                current_episode.tags.add(group_key)

            last_time = event.timestamp

        return episodes

    def _segment_by_key(self, sorted_events: list[Event], key_kind: str) -> list[Episode]:
        """Strict grouping: one episode per distinct thread/meeting id.

        Events carrying the key stay together no matter how far apart in
        time they are. Events without it fall back to plain gap
        segmentation among themselves, with thread and meeting grouping
        disabled so a strict mode never regroups by the other key. The
        ``max_episode_events`` cap splits oversized key groups into
        consecutive episodes. Output is sorted by (start_time,
        episode_id), so runs over the same input are identical.
        """
        field_name = f"{key_kind}_id"
        keyed: dict[str, list[Event]] = {}
        unkeyed: list[Event] = []
        for event in sorted_events:
            key = event.content.get(field_name)
            if key is None:
                unkeyed.append(event)
            else:
                keyed.setdefault(f"{key_kind}:{key}", []).append(event)
        episodes: list[Episode] = []
        for group in sorted(keyed):
            current: Episode | None = None
            for event in keyed[group]:
                if current is None or self._is_full(current):
                    current = self._start_episode(event)
                    current.tags.add(group)
                    episodes.append(current)
                else:
                    current.add_event(event)
        if unkeyed:
            fallback = EpisodeSegmenter(
                gap_minutes=self.gap_minutes,
                group_by_thread=False,
                group_by_meeting=False,
                max_episode_events=self.max_episode_events,
                mode="gap",
                day_tz=self.day_tz,
            )
            episodes.extend(fallback._segment_gap(unkeyed))
        episodes.sort(key=lambda ep: (ep.start_time, ep.episode_id))
        return episodes

    def _segment_by_day(self, sorted_events: list[Event]) -> list[Episode]:
        """One episode per (local calendar day, thread/meeting) bucket.

        Days are bucketed in ``day_tz`` so histories spanning DST changes
        keep events on their local day. Buckets are emitted in (day,
        group) order, which is deterministic for any fixed input. The
        ``max_episode_events`` cap applies to gap mode only; day buckets
        stay whole so a day is always reconstructable as one unit.
        """
        tz = ZoneInfo(self.day_tz)
        buckets: dict[tuple[str, str], list[Event]] = {}
        for event in sorted_events:
            day = event.timestamp.astimezone(tz).date().isoformat()
            key = (day, self._group_key(event) or "")
            buckets.setdefault(key, []).append(event)
        episodes: list[Episode] = []
        for day, _group in sorted(buckets):
            first, *rest = buckets[(day, _group)]
            episode = self._start_episode(first)
            for event in rest:
                episode.add_event(event)
            episode.tags.add(f"day:{day}")
            episodes.append(episode)
        return episodes

    def _group_key(self, event: Event) -> str | None:
        d = event.content
        if self.group_by_thread and "thread_id" in d:
            return "thread:" + str(d["thread_id"])
        if self.group_by_meeting and "meeting_id" in d:
            return "meeting:" + str(d["meeting_id"])
        return None

    def _is_full(self, episode: Episode) -> bool:
        return self.max_episode_events > 0 and len(episode.events) >= self.max_episode_events

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
            return str(d["subject"])
        if "title" in d:
            return str(d["title"])
        if event.event_type == EventType.FOCUS_BLOCK:
            return f"Focus: {d.get('activity', 'work')}"
        return str(event.event_type)

    def _gap_exceeds(self, t1: datetime | None, t2: datetime) -> bool:
        if t1 is None:
            return False
        dt1 = t1 if t1.tzinfo is not None else t1.replace(tzinfo=UTC)
        dt2 = t2 if t2.tzinfo is not None else t2.replace(tzinfo=UTC)
        return (dt2 - dt1) > timedelta(minutes=self.gap_minutes)


_MentionT = TypeVar("_MentionT")


def _dedupe_mentions(
    found: list[_MentionT],
    key: Callable[[_MentionT], tuple[Any, ...]],
    confidence_of: Callable[[_MentionT], float],
    sort_key: Callable[[_MentionT], tuple[Any, ...]],
    min_confidence: float,
) -> list[_MentionT]:
    """Keep the highest-confidence mention per key, then filter and sort.

    Shared by the commitment and decision extractors so both dedupe with
    identical, deterministic semantics.
    """
    best: dict[tuple[Any, ...], _MentionT] = {}
    for mention in found:
        mention_key = key(mention)
        current = best.get(mention_key)
        if current is None or confidence_of(mention) > confidence_of(current):
            best[mention_key] = mention
    kept = [m for m in best.values() if confidence_of(m) >= min_confidence]
    kept.sort(key=sort_key)
    return kept


# --- Commitment extraction -------------------------------------------------

_ISO_DATE = r"\d{4}-\d{2}-\d{2}"

# Relative due phrases, resolved against the event timestamp's local day.
_RELATIVE_DUE = (
    r"tomorrow|eod|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|next\s+week|end\s+of\s+week"
)
_DUE = rf"(?P<due>{_ISO_DATE}|(?i:{_RELATIVE_DUE}))"
_COUNTED_DUE = r"(?P<due>in\s+\d{1,3}\s+(?:days?|weeks?))"

_WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def resolve_relative_due(phrase: str, now: datetime) -> str | None:
    """Resolve a relative due phrase to an ISO date, or None if unknown.

    Deterministic rules (documented for auditability):

    * ``tomorrow`` -> the day after the event's local day;
    * ``eod`` -> the event's local day;
    * a weekday name -> the next occurrence strictly after the event day;
    * ``next week`` -> Monday of the following week;
    * ``end of week`` -> the next Friday strictly after the event day;
    * ``in N day(s)/week(s)`` -> the event day plus N days/weeks.
    """
    normalized = " ".join(phrase.lower().split())
    day = now.date()
    if normalized == "tomorrow":
        return (day + timedelta(days=1)).isoformat()
    if normalized == "eod":
        return day.isoformat()
    if normalized in _WEEKDAY_INDEX:
        delta = (_WEEKDAY_INDEX[normalized] - day.weekday()) % 7 or 7
        return (day + timedelta(days=delta)).isoformat()
    if normalized == "next week":
        return (day + timedelta(days=7 - day.weekday())).isoformat()
    if normalized == "end of week":
        return (day + timedelta(days=(4 - day.weekday()) % 7 or 7)).isoformat()
    counted = re.fullmatch(r"in (\d{1,3}) (days?|weeks?)", normalized)
    if counted:
        units = 7 if counted.group(2).startswith("week") else 1
        return (day + timedelta(days=int(counted.group(1)) * units)).isoformat()
    return None


# (pattern, confidence, direction). Direction decides who owes whom:
#   self    -> the event actor owes ("I will ...")
#   request -> the counterparty owes ("please ... by")
#   task    -> the assignee (or actor) owes ("action item: ...")
_COMMITMENT_PATTERNS: tuple[tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(rf"[Ii] owe (?:you|(?P<creditor>[\w.-]+)):?\s*(?P<what>.+?)\s+by\s+{_DUE}"),
        0.95,
        "self",
    ),
    (
        re.compile(rf"[Ii] will\s+(?P<what>.+?)\s+by\s+{_DUE}"),
        0.85,
        "self",
    ),
    (
        re.compile(rf"[Ii] will\s+(?P<what>.+?)\s+{_COUNTED_DUE}\.?\s*$", re.MULTILINE),
        0.85,
        "self",
    ),
    (
        re.compile(rf"[Ii]'ll\s+(?P<what>.+?)\s+by\s+{_DUE}"),
        0.8,
        "self",
    ),
    (
        re.compile(rf"[Pp]lease\s+(?P<what>.+?)\s+by\s+{_DUE}"),
        0.7,
        "request",
    ),
    (
        re.compile(
            rf"[Aa]ction item:?\s*(?P<what>.+?)(?:\s+by\s+{_DUE})?\s*$",
            re.MULTILINE,
        ),
        0.6,
        "task",
    ),
)

_TEXT_FIELDS = ("body", "notes", "content", "text", "subject")


@dataclass(slots=True)
class EvidenceSpan:
    """Exact location of extracted evidence inside a source event."""

    event_id: str
    field: str
    start: int
    end: int
    quote: str

    def resolves_in(self, event: Event) -> bool:
        """Check the span still points at its quoted text (both directions)."""
        text = event.content.get(self.field)
        return isinstance(text, str) and text[self.start : self.end] == self.quote


@dataclass(slots=True)
class CommitmentMention:
    """A commitment signal found in one event: who owes whom what by when."""

    debtor: str
    creditor: str
    description: str
    due: str | None
    confidence: float
    evidence: EvidenceSpan


def _event_actor(event: Event) -> str:
    """Best-effort actor of an event (the person who produced it)."""
    c = event.content
    for key in ("persona_id", "sender", "author", "assignee", "from"):
        value = c.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _event_counterparty(event: Event) -> str:
    """Best-effort counterparty (first recipient/addressee/attendee)."""
    c = event.content
    for key in ("recipients", "to", "attendees"):
        value = c.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
    return ""


@dataclass
class CommitmentExtractor:
    """Rule-based commitment extraction with auditable evidence spans.

    Two extraction paths, both deterministic:

    * structured: events carrying an explicit ``commitment_ref`` together
      with a commitment signal (a ``Commitment:`` subject or a
      ``commitment_ack`` event) yield confidence 1.0 mentions;
    * textual: transparent regex patterns over text payload fields, each
      with a fixed confidence reflecting phrase strength.

    Every mention records the exact source span it was derived from, so
    extraction can be reconstructed against the original event text.
    """

    min_confidence: float = 0.0

    def extract(self, event: Event) -> list[CommitmentMention]:
        found: list[CommitmentMention] = []
        structured = self._from_structured(event)
        if structured is not None:
            found.append(structured)
        actor = _event_actor(event)
        counter = _event_counterparty(event)
        for field_name in _TEXT_FIELDS:
            text = event.content.get(field_name)
            if not isinstance(text, str):
                continue
            for pattern, confidence, direction in _COMMITMENT_PATTERNS:
                for m in pattern.finditer(text):
                    found.append(
                        self._build(m, event, field_name, confidence, direction, actor, counter)
                    )
        return self._dedupe(found)

    def extract_all(self, events: Iterable[Event]) -> list[CommitmentMention]:
        mentions: list[CommitmentMention] = []
        for event in events:
            mentions.extend(self.extract(event))
        return mentions

    def _build(
        self,
        m: re.Match[str],
        event: Event,
        field_name: str,
        confidence: float,
        direction: str,
        actor: str,
        counter: str,
    ) -> CommitmentMention:
        groups = m.groupdict()
        what = (groups.get("what") or "").strip().rstrip(".").strip()
        due = groups.get("due")
        if due is not None and not re.fullmatch(_ISO_DATE, due):
            due = resolve_relative_due(due, event.timestamp)
        creditor_named = groups.get("creditor") or ""
        if direction == "self":
            debtor, creditor = actor, creditor_named or counter
        elif direction == "request":
            debtor, creditor = counter, actor
        else:
            debtor = str(event.content.get("assignee") or actor)
            creditor = counter
        return CommitmentMention(
            debtor=debtor,
            creditor=creditor,
            description=what,
            due=due,
            confidence=confidence,
            evidence=EvidenceSpan(
                event_id=event.event_id,
                field=field_name,
                start=m.start(),
                end=m.end(),
                quote=m.group(0),
            ),
        )

    def _from_structured(self, event: Event) -> CommitmentMention | None:
        ref = event.content.get("commitment_ref")
        if not isinstance(ref, str) or not ref:
            return None
        subject = str(event.content.get("subject", ""))
        is_ack = event.event_type == EventType.COMMITMENT_ACK
        if not (is_ack or subject.startswith("Commitment:")):
            return None
        description = subject.removeprefix("Commitment:").strip()
        if not description:
            description = str(event.content.get("description", "")) or ref
        due: str | None = None
        body = str(event.content.get("body", ""))
        due_match = re.search(rf"\b(?:by|deadline:)\s*({_ISO_DATE})", body, re.IGNORECASE)
        if due_match:
            due = due_match.group(1)
        return CommitmentMention(
            debtor=_event_actor(event),
            creditor=_event_counterparty(event),
            description=description,
            due=due,
            confidence=1.0,
            evidence=EvidenceSpan(
                event_id=event.event_id,
                field="commitment_ref",
                start=0,
                end=len(ref),
                quote=ref,
            ),
        )

    def _dedupe(self, found: list[CommitmentMention]) -> list[CommitmentMention]:
        return _dedupe_mentions(
            found,
            key=lambda m: (m.debtor, m.creditor, m.description, m.due),
            confidence_of=lambda m: m.confidence,
            sort_key=lambda m: (m.evidence.field, m.evidence.start, m.description),
            min_confidence=self.min_confidence,
        )


# --- Decision extraction ----------------------------------------------------

_DECISION_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (
        re.compile(
            r"[Ww]e decided to\s+(?P<what>.+?)(?:\s+because\s+(?P<why>.+?))?\s*$",
            re.MULTILINE,
        ),
        0.85,
    ),
    (
        re.compile(
            r"[Ww]e chose\s+(?P<what>.+?)(?:\s+because\s+(?P<why>.+?))?\s*$",
            re.MULTILINE,
        ),
        0.8,
    ),
    (
        re.compile(r"[Dd]ecision:\s*(?P<what>.+?)$", re.MULTILINE),
        0.75,
    ),
)


@dataclass(slots=True)
class DecisionMention:
    """A decision signal found in one event."""

    title: str
    project: str
    rationale: str
    confidence: float
    evidence: EvidenceSpan


@dataclass
class DecisionExtractor:
    """Rule-based decision extraction mirroring the commitment extractor.

    Structured path: events carrying a ``decision_ref`` with a
    ``Decision record:`` title yield confidence 1.0 mentions.  Textual
    path: transparent patterns over text payload fields.
    """

    min_confidence: float = 0.0

    def extract(self, event: Event) -> list[DecisionMention]:
        found: list[DecisionMention] = []
        structured = self._from_structured(event)
        if structured is not None:
            found.append(structured)
        project = str(event.content.get("project", ""))
        for field_name in _TEXT_FIELDS:
            text = event.content.get(field_name)
            if not isinstance(text, str):
                continue
            for pattern, confidence in _DECISION_PATTERNS:
                for m in pattern.finditer(text):
                    groups = m.groupdict()
                    found.append(
                        DecisionMention(
                            title=(groups.get("what") or "").strip().rstrip(".").strip(),
                            project=project,
                            rationale=(groups.get("why") or "").strip(),
                            confidence=confidence,
                            evidence=EvidenceSpan(
                                event_id=event.event_id,
                                field=field_name,
                                start=m.start(),
                                end=m.end(),
                                quote=m.group(0),
                            ),
                        )
                    )
        return self._dedupe(found)

    def extract_all(self, events: Iterable[Event]) -> list[DecisionMention]:
        mentions: list[DecisionMention] = []
        for event in events:
            mentions.extend(self.extract(event))
        return mentions

    def _from_structured(self, event: Event) -> DecisionMention | None:
        ref = event.content.get("decision_ref")
        if not isinstance(ref, str) or not ref:
            return None
        title = str(event.content.get("title", ""))
        if not title.startswith("Decision record:"):
            return None
        project = str(event.content.get("project", ""))
        if not project:
            project = title.removeprefix("Decision record:").strip()
        return DecisionMention(
            title=title,
            project=project,
            rationale=str(event.content.get("content", "")),
            confidence=1.0,
            evidence=EvidenceSpan(
                event_id=event.event_id,
                field="decision_ref",
                start=0,
                end=len(ref),
                quote=ref,
            ),
        )

    def _dedupe(self, found: list[DecisionMention]) -> list[DecisionMention]:
        return _dedupe_mentions(
            found,
            key=lambda m: (m.title, m.project),
            confidence_of=lambda m: m.confidence,
            sort_key=lambda m: (m.evidence.field, m.evidence.start, m.title),
            min_confidence=self.min_confidence,
        )


# --- Document reference extraction ------------------------------------------

_DOC_TEXT_REF = re.compile(r"\bdoc-[A-Za-z0-9]+-\d+\b")
_DOC_URI_REF = re.compile(r"\bdoc://([A-Za-z0-9_.-]+)")

# Lower number wins when the same doc id is seen through several paths.
_DOC_KIND_PRIORITY = {"structured": 0, "uri": 1, "text": 2}


@dataclass(slots=True)
class DocumentReference:
    """A link from one event to one document node."""

    doc_id: str
    kind: str  # structured | uri | text
    evidence: EvidenceSpan


@dataclass
class DocumentReferenceExtractor:
    """Collects document links so ingestion can wire events to doc nodes.

    Three deterministic paths, in decreasing precedence:

    * structured: the event's own ``doc_id`` field (document changes);
    * uri: ``doc://<id>`` references inside text fields;
    * text: bare ``doc-<project>-<n>`` identifiers inside text fields.

    One reference per (event, doc id) survives; its evidence span always
    resolves inside the source event.
    """

    def extract(self, event: Event) -> list[DocumentReference]:
        best: dict[str, DocumentReference] = {}

        def offer(ref: DocumentReference) -> None:
            current = best.get(ref.doc_id)
            if current is None or _DOC_KIND_PRIORITY[ref.kind] < _DOC_KIND_PRIORITY[current.kind]:
                best[ref.doc_id] = ref

        doc_id = event.content.get("doc_id")
        if isinstance(doc_id, str) and doc_id:
            offer(
                DocumentReference(
                    doc_id=doc_id,
                    kind="structured",
                    evidence=EvidenceSpan(
                        event_id=event.event_id,
                        field="doc_id",
                        start=0,
                        end=len(doc_id),
                        quote=doc_id,
                    ),
                )
            )
        for field_name in _TEXT_FIELDS:
            text = event.content.get(field_name)
            if not isinstance(text, str):
                continue
            covered: list[range] = []
            for m in _DOC_URI_REF.finditer(text):
                covered.append(range(m.start(), m.end()))
                offer(
                    DocumentReference(
                        doc_id=m.group(1),
                        kind="uri",
                        evidence=EvidenceSpan(
                            event_id=event.event_id,
                            field=field_name,
                            start=m.start(),
                            end=m.end(),
                            quote=m.group(0),
                        ),
                    )
                )
            for m in _DOC_TEXT_REF.finditer(text):
                if any(m.start() in span for span in covered):
                    continue  # already captured as part of a doc:// uri
                offer(
                    DocumentReference(
                        doc_id=m.group(0),
                        kind="text",
                        evidence=EvidenceSpan(
                            event_id=event.event_id,
                            field=field_name,
                            start=m.start(),
                            end=m.end(),
                            quote=m.group(0),
                        ),
                    )
                )
        return [best[doc] for doc in sorted(best)]

    def extract_all(self, events: Iterable[Event]) -> list[DocumentReference]:
        refs: list[DocumentReference] = []
        for event in events:
            refs.extend(self.extract(event))
        return refs


# --- Cited reconstruction ----------------------------------------------------

_TRANSCRIPT_CITATION = re.compile(r"^\((?P<event_id>evt_[0-9a-f]+)#(?P<field>\w+)\)")


@dataclass(slots=True)
class ReconstructedSpan:
    """One cited piece of an episode's source text."""

    event_id: str
    field: str
    quote: str


@dataclass
class EpisodeReconstructor:
    """Rebuilds readable, fully cited transcripts from episodes.

    The transcript is the inverse of segmentation: every non-empty text
    field of every event becomes one cited span, and each transcript line
    carries the event id it came from, so a reader (or an audit) can walk
    from the reconstruction back to the exact source payload.
    """

    max_quote_chars: int = 240
    fields: tuple[str, ...] = _TEXT_FIELDS

    def spans(self, episode: Episode) -> list[ReconstructedSpan]:
        spans: list[ReconstructedSpan] = []
        for event in episode.events:
            for field_name in self.fields:
                text = event.content.get(field_name)
                if isinstance(text, str) and text.strip():
                    spans.append(
                        ReconstructedSpan(
                            event_id=event.event_id,
                            field=field_name,
                            quote=text[: self.max_quote_chars],
                        )
                    )
        return spans

    def transcript(self, episode: Episode) -> str:
        """Markdown transcript; every content line cites (event_id#field)."""
        lines = [f"# {episode.title}", ""]
        for span in self.spans(episode):
            quote = " ".join(span.quote.split())
            lines.append(f"- ({span.event_id}#{span.field}) {quote}")
        return "\n".join(lines) + "\n"

    def cited_event_ids(self, transcript: str) -> list[str]:
        """Event ids cited by a transcript, in order of first citation."""
        seen: dict[str, None] = {}
        for line in transcript.splitlines():
            body = line.removeprefix("- ")
            m = _TRANSCRIPT_CITATION.match(body)
            if m:
                seen.setdefault(m.group("event_id"), None)
        return list(seen)


# --- Ingestion pipeline facade ------------------------------------------------


@dataclass(slots=True)
class IngestStats:
    """Counts summarizing one ingestion run."""

    event_count: int
    episode_count: int
    entity_count: int
    commitment_count: int
    decision_count: int
    document_reference_count: int


@dataclass(slots=True)
class IngestResult:
    """Everything one ingestion run produced, with a stable digest."""

    episodes: list[Episode]
    entities: list[Entity]
    commitments: list[CommitmentMention]
    decisions: list[DecisionMention]
    documents: list[DocumentReference]
    event_count: int

    def stats(self) -> IngestStats:
        return IngestStats(
            event_count=self.event_count,
            episode_count=len(self.episodes),
            entity_count=len(self.entities),
            commitment_count=len(self.commitments),
            decision_count=len(self.decisions),
            document_reference_count=len(self.documents),
        )

    def digest(self) -> str:
        """SHA-256 over the canonical summary of this result.

        Equal inputs and configuration always produce the same digest;
        confidence values are quantized so the digest stays stable across
        platforms.
        """
        payload = {
            "events": self.event_count,
            "episodes": [e.episode_id for e in self.episodes],
            "entities": [entity.entity_id for entity in self.entities],
            "commitments": [
                [m.debtor, m.creditor, m.description, m.due, round(m.confidence, 6)]
                for m in self.commitments
            ],
            "decisions": [[m.title, m.project, round(m.confidence, 6)] for m in self.decisions],
            "documents": [[r.doc_id, r.kind] for r in self.documents],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class IngestPipeline:
    """Runs the full ingestion chain over a batch of events.

    Stages: deterministic ordering -> episode segmentation -> entity
    harvest -> commitment / decision / document extraction. The pipeline
    is pure: the same events and configuration always yield the same
    ``IngestResult`` digest.
    """

    segmenter: EpisodeSegmenter = field(default_factory=EpisodeSegmenter)
    commitments: CommitmentExtractor = field(default_factory=CommitmentExtractor)
    decisions: DecisionExtractor = field(default_factory=DecisionExtractor)
    documents: DocumentReferenceExtractor = field(default_factory=DocumentReferenceExtractor)
    aliases: AliasTable = field(default_factory=AliasTable)

    def run(self, events: Iterable[Event]) -> IngestResult:
        ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id))
        episodes = self.segmenter.segment(ordered)
        entities = self._harvest_entities(ordered)
        return IngestResult(
            episodes=episodes,
            entities=entities,
            commitments=self.commitments.extract_all(ordered),
            decisions=self.decisions.extract_all(ordered),
            documents=self.documents.extract_all(ordered),
            event_count=len(ordered),
        )

    def _harvest_entities(self, events: list[Event]) -> list[Entity]:
        people: set[str] = set()
        projects: set[str] = set()
        for event in events:
            content = event.content
            for key in ("sender", "author", "assignee", "owner", "persona_id"):
                value = content.get(key)
                if isinstance(value, str) and value:
                    people.add(value)
            for key in ("recipients", "attendees"):
                value = content.get(key)
                if isinstance(value, list):
                    people.update(str(item) for item in value if item)
            project = content.get("project")
            if isinstance(project, str) and project:
                projects.add(project)
        entities: list[Entity] = []
        for name in sorted(people):
            entities.append(self._register(f"person:{name}", "person", name))
        for name in sorted(projects):
            entities.append(self._register(f"project:{name}", "project", name))
        return entities

    def _register(self, entity_id: str, entity_type: str, name: str) -> Entity:
        existing = self.aliases.get(entity_id)
        if existing is not None:
            return existing
        entity = Entity(entity_id=entity_id, entity_type=entity_type, name=name)
        self.aliases.add_entity(entity)
        return entity
