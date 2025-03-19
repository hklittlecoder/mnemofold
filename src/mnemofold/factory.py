"""Synthetic work-history factory.

Seeded personas generate deterministic 180-day work histories of mail
threads, meetings, notes, documents, and task updates.  Histories
include planted commitments (with due dates), planted decisions,
planted contradictions (changed deadlines, reassigned owners,
conflicting decisions), and repeated workflows for playbook mining.
All output is reproducible from a seed and a manifest.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from mnemofold.events import Event, EventType


class PersonaRole(StrEnum):
    PM = "product_manager"
    ENGINEER = "engineer"
    RESEARCHER = "researcher"
    DESIGNER = "designer"


class WorkdayPattern(StrEnum):
    STANDARD_9TO5 = "standard_9to5"
    FLEXIBLE = "flexible"
    SHIFT_EARLY = "shift_early"
    SHIFT_LATE = "shift_late"


@dataclass
class Persona:
    person_id: str
    name: str
    role: PersonaRole
    timezone: str = "UTC"
    workday: WorkdayPattern = WorkdayPattern.STANDARD_9TO5
    team: str = "default"
    projects: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SyntheticEvent:
    event_id: str
    event_type: str
    timestamp: str
    payload: dict

    def to_event(self) -> Event:
        """Convert to a typed, content-addressed Event.

        The content-addressed ``event_id`` is recomputed from the payload,
        so it differs from the factory-assigned sequential id; callers that
        need the mapping should keep both.
        """
        return Event(
            EventType(self.event_type),
            datetime.fromisoformat(self.timestamp),
            dict(self.payload),
        )


@dataclass
class PlantedItem:
    item_id: str
    kind: str  # commitment, decision, contradiction
    data: dict


@dataclass
class HistoryManifest:
    seed: int
    days: int
    start_date: str
    personas: list[str]
    projects: list[str]
    event_count: int
    planted_commitments: int
    planted_decisions: int
    planted_contradictions: int
    checksum: str = ""


class WorkHistoryFactory:
    """Generates a deterministic synthetic work history.

    Given a seed and configuration, produces a list of events spanning
    ``days`` days, along with a manifest describing planted ground
    truth for evaluation.
    """

    def __init__(self, seed: int = 42, days: int = 180) -> None:
        self.seed = seed
        self.days = days
        self.start_date = datetime(2025, 1, 1, tzinfo=UTC)
        self.personas: list[Persona] = []
        self.projects: list[str] = []
        self._rng: random.Random = random.Random(seed)
        self._events: list[SyntheticEvent] = []
        self._planted: list[PlantedItem] = []

    def add_persona(self, persona: Persona) -> None:
        self.personas.append(persona)

    def add_project(self, name: str) -> None:
        self.projects.append(name)

    def generate(self) -> tuple[list[SyntheticEvent], HistoryManifest]:
        self._rng = random.Random(self.seed)
        self._events = []
        self._planted = []

        if not self.personas:
            self._default_personas()
        if not self.projects:
            self._default_projects()

        for day in range(self.days):
            day_date = self.start_date + timedelta(days=day)
            if day_date.weekday() >= 5:  # weekends get lighter load
                self._generate_weekend_day(day_date)
            else:
                self._generate_workday(day_date)

        self._plant_commitments()
        self._plant_decisions()
        self._plant_contradictions()

        self._events.sort(key=lambda e: e.timestamp)
        self._assign_ids()

        manifest = HistoryManifest(
            seed=self.seed,
            days=self.days,
            start_date=self.start_date.isoformat(),
            personas=[p.person_id for p in self.personas],
            projects=list(self.projects),
            event_count=len(self._events),
            planted_commitments=sum(1 for p in self._planted if p.kind == "commitment"),
            planted_decisions=sum(1 for p in self._planted if p.kind == "decision"),
            planted_contradictions=sum(1 for p in self._planted if p.kind == "contradiction"),
            checksum=self._compute_checksum(),
        )
        return self._events, manifest

    def planted_items(self) -> list[PlantedItem]:
        return list(self._planted)

    def _default_personas(self) -> None:
        self.add_persona(
            Persona("p1", "Alice Chen", PersonaRole.PM, team="core", projects=["alpha", "beta"])
        )
        self.add_persona(
            Persona("p2", "Bob Li", PersonaRole.ENGINEER, team="core", projects=["alpha"])
        )
        self.add_persona(
            Persona("p3", "Carol Wang", PersonaRole.RESEARCHER, team="research", projects=["beta"])
        )

    def _default_projects(self) -> None:
        self.projects = ["alpha", "beta", "gamma"]

    def _generate_workday(self, day_date: datetime) -> None:
        rng = self._rng
        for persona in self.personas:
            base_hour = self._work_start_hour(persona)
            # Each persona generates 3-8 events per workday
            count = rng.randint(3, 8)
            for _ in range(count):
                hour_offset = rng.uniform(0, 8)
                ts = day_date + timedelta(hours=base_hour + hour_offset)
                event_type = self._pick_event_type(rng, persona)
                self._make_event(event_type, persona, ts)

    def _generate_weekend_day(self, day_date: datetime) -> None:
        rng = self._rng
        for persona in self.personas:
            if rng.random() < 0.3:  # 30% chance of weekend activity
                ts = day_date + timedelta(hours=rng.uniform(10, 16))
                self._make_event("note", persona, ts)

    def _work_start_hour(self, persona: Persona) -> int:
        if persona.workday == WorkdayPattern.SHIFT_EARLY:
            return 7
        if persona.workday == WorkdayPattern.SHIFT_LATE:
            return 11
        return 9

    def _pick_event_type(self, rng: random.Random, persona: Persona) -> str:
        types = {
            PersonaRole.PM: [
                "mail_received",
                "mail_sent",
                "meeting_scheduled",
                "meeting_held",
                "note",
                "task_update",
                "document_change",
            ],
            PersonaRole.ENGINEER: [
                "mail_received",
                "mail_sent",
                "task_update",
                "document_change",
                "note",
                "focus_block",
                "chat_message",
            ],
            PersonaRole.RESEARCHER: [
                "note",
                "document_change",
                "mail_received",
                "mail_sent",
                "meeting_held",
            ],
            PersonaRole.DESIGNER: ["document_change", "note", "meeting_held", "mail_sent"],
        }
        pool = types.get(persona.role, types[PersonaRole.ENGINEER])
        return rng.choice(pool)

    def _make_event(self, event_type: str, persona: Persona, ts: datetime) -> None:
        rng = self._rng
        project = rng.choice(persona.projects) if persona.projects else "general"
        payload: dict = {
            "persona_id": persona.person_id,
            "persona_name": persona.name,
            "project": project,
        }

        if event_type == "mail_received":
            payload.update(
                {
                    "from": rng.choice(
                        [
                            "alice@co.example",
                            "bob@co.example",
                            "carol@co.example",
                            "external@vendor.example",
                        ]
                    ),
                    "to": [f"{persona.person_id}@co.example"],
                    "subject": f"Re: {project} update #{rng.randint(1, 100)}",
                    "body": f"This is a synthetic email about {project}. It discusses progress and next steps.",
                    "thread_id": f"thread-{rng.randint(1, 200)}",
                }
            )
        elif event_type == "mail_sent":
            payload.update(
                {
                    "from": f"{persona.person_id}@co.example",
                    "to": [f"p{rng.randint(1, 9)}@co.example"],
                    "subject": f"Update on {project}",
                    "body": f"Sending an update about {project} status.",
                    "thread_id": f"thread-{rng.randint(1, 200)}",
                }
            )
        elif event_type == "meeting_scheduled":
            payload.update(
                {
                    "meeting_title": f"{project} sync",
                    "attendees": [persona.person_id]
                    + [f"p{rng.randint(1, 9)}" for _ in range(rng.randint(1, 3))],
                    "duration_min": rng.choice([15, 30, 45, 60]),
                    "location": "zoom",
                }
            )
        elif event_type == "meeting_held":
            payload.update(
                {
                    "meeting_title": f"{project} review",
                    "attendees": [persona.person_id, f"p{rng.randint(1, 9)}"],
                    "duration_min": rng.choice([30, 45, 60]),
                    "notes": f"Discussed {project} milestones and blockers.",
                }
            )
        elif event_type == "note":
            payload.update(
                {
                    "title": f"Note: {project} thoughts",
                    "content": f"Quick note about {project}: {rng.randint(10, 99)} items to consider.",
                    "tags": [project, rng.choice(["idea", "todo", "reflection"])],
                }
            )
        elif event_type == "task_update":
            payload.update(
                {
                    "task_id": f"task-{project}-{rng.randint(1, 50)}",
                    "status": rng.choice(["in_progress", "blocked", "done"]),
                    "progress_pct": rng.randint(0, 100),
                }
            )
        elif event_type == "document_change":
            payload.update(
                {
                    "doc_id": f"doc-{project}-{rng.randint(1, 30)}",
                    "change_type": rng.choice(["create", "update", "comment"]),
                    "summary": f"Updated document for {project}",
                }
            )
        elif event_type == "chat_message":
            payload.update(
                {
                    "channel": f"#{project}",
                    "message": f"Quick update on {project}",
                    "channel_type": rng.choice(["public", "private"]),
                }
            )
        elif event_type == "focus_block":
            payload.update(
                {
                    "duration_min": rng.choice([25, 50, 90]),
                    "focus_area": project,
                    "interruptions": rng.randint(0, 3),
                }
            )
        elif event_type == "commitment_acknowledged":
            payload.update(
                {
                    "about": project,
                    "commitment_id": f"c-{rng.randint(1, 100)}",
                }
            )

        self._events.append(
            SyntheticEvent(
                event_id="",
                event_type=event_type,
                timestamp=ts.isoformat(),
                payload=payload,
            )
        )

    def _plant_commitments(self) -> None:
        rng = self._rng
        count = min(max(2, self.days // 15), 20)
        for i in range(count):
            day_offset = rng.randint(0, max(0, self.days - 2))
            remaining = max(1, self.days - day_offset - 1)
            due_gap = rng.randint(1, min(30, remaining))
            due_offset = day_offset + due_gap
            owner = rng.choice(self.personas)
            project = rng.choice(owner.projects) if owner.projects else "general"
            cid = f"planted-commitment-{i}"
            ts = (self.start_date + timedelta(days=day_offset)).isoformat()
            due = (self.start_date + timedelta(days=due_offset)).isoformat()
            item = PlantedItem(
                item_id=cid,
                kind="commitment",
                data={
                    "owed_by": owner.person_id,
                    "owed_to": f"p{rng.randint(1, 9)}",
                    "description": f"Complete {project} milestone {i}",
                    "due_date": due,
                    "project": project,
                },
            )
            self._planted.append(item)
            # Also emit an event that references this commitment
            self._events.append(
                SyntheticEvent(
                    event_id="",
                    event_type="mail_sent",
                    timestamp=ts,
                    payload={
                        "persona_id": owner.person_id,
                        "from": f"{owner.person_id}@co.example",
                        "subject": f"Commitment: {item.data['description']}",
                        "body": f"I owe you: {item.data['description']} by {due}.",
                        "commitment_ref": cid,
                        "project": project,
                    },
                )
            )

    def _plant_decisions(self) -> None:
        rng = self._rng
        count = min(max(1, self.days // 45), 15)
        for i in range(count):
            day_offset = rng.randint(0, max(1, self.days - 1))
            ts = (self.start_date + timedelta(days=day_offset)).isoformat()
            project = rng.choice(self.projects)
            did = f"planted-decision-{i}"
            n_options = rng.randint(2, 4)
            item = PlantedItem(
                item_id=did,
                kind="decision",
                data={
                    "title": f"Decision: {project} approach #{i}",
                    "project": project,
                    "made_by": rng.choice([p.person_id for p in self.personas]),
                    "options_considered": [f"opt-{j}" for j in range(n_options)],
                    "chosen_index": rng.randint(0, n_options - 1),
                    "rationale": f"Selected based on {project} priorities.",
                },
            )
            self._planted.append(item)
            self._events.append(
                SyntheticEvent(
                    event_id="",
                    event_type="note",
                    timestamp=ts,
                    payload={
                        "title": f"Decision record: {project}",
                        "content": f"Decision made about {project}.",
                        "decision_ref": did,
                        "project": project,
                    },
                )
            )

    def _plant_contradictions(self) -> None:
        rng = self._rng
        count = min(max(1, self.days // 60), 10)
        for i in range(count):
            commitments = [p for p in self._planted if p.kind == "commitment"]
            if not commitments:
                break
            target = rng.choice(commitments)
            original_due = target.data["due_date"]
            due_dt = datetime.fromisoformat(original_due)
            shift_days = rng.choice([-3, -1, 5, 7])
            new_due_dt = due_dt + timedelta(days=shift_days)
            notify_before = min(3, max(1, (due_dt - self.start_date).days - 1))
            ts_dt = due_dt - timedelta(days=notify_before)
            cid = f"planted-contradiction-{i}"
            item = PlantedItem(
                item_id=cid,
                kind="contradiction",
                data={
                    "target_commitment": target.item_id,
                    "change": "due_date",
                    "old_value": original_due,
                    "new_value": new_due_dt.isoformat(),
                    "reason": rng.choice(["scope change", "resource shift", "priority change"]),
                },
            )
            self._planted.append(item)
            self._events.append(
                SyntheticEvent(
                    event_id="",
                    event_type="mail_sent",
                    timestamp=ts_dt.isoformat(),
                    payload={
                        "from": f"{target.data['owed_by']}@co.example",
                        "subject": "Updating deadline",
                        "body": f"New deadline: {new_due_dt.date()}",
                        "commitment_ref": target.item_id,
                        "contradiction_ref": cid,
                        "project": target.data["project"],
                    },
                )
            )

    def _assign_ids(self) -> None:
        for i, ev in enumerate(self._events):
            ev.event_id = f"evt-{i:06d}"

    def _compute_checksum(self) -> str:
        h = hashlib.sha256()
        for ev in self._events:
            h.update(ev.event_id.encode())
            h.update(ev.timestamp.encode())
            h.update(ev.event_type.encode())
        return h.hexdigest()[:16]
