from datetime import datetime

from mnemofold.factory import (
    Persona,
    PersonaRole,
    PlantedItem,
    SyntheticEvent,
    WorkdayPattern,
    WorkHistoryFactory,
)


def test_persona_defaults():
    p = Persona("p1", "Test", PersonaRole.ENGINEER)
    assert p.timezone == "UTC"
    assert p.workday == WorkdayPattern.STANDARD_9TO5
    assert p.projects == []
    assert p.team == "default"


def test_factory_empty_no_personas():
    f = WorkHistoryFactory(seed=1, days=5)
    events, manifest = f.generate()
    assert len(events) > 0
    assert manifest.days == 5
    assert manifest.seed == 1
    assert len(manifest.personas) == 3  # default personas


def test_factory_deterministic():
    f1 = WorkHistoryFactory(seed=42, days=30)
    e1, m1 = f1.generate()

    f2 = WorkHistoryFactory(seed=42, days=30)
    e2, m2 = f2.generate()

    assert len(e1) == len(e2)
    assert m1.event_count == m2.event_count
    assert m1.checksum == m2.checksum
    for a, b in zip(e1, e2, strict=False):
        assert a.event_id == b.event_id
        assert a.timestamp == b.timestamp
        assert a.event_type == b.event_type
        assert a.payload == b.payload


def test_factory_different_seeds_diverge():
    f1 = WorkHistoryFactory(seed=1, days=10)
    e1, _ = f1.generate()
    f2 = WorkHistoryFactory(seed=2, days=10)
    e2, _ = f2.generate()
    # Different seeds should produce different checksums
    hashes = set()
    for f in (f1, f2):
        events, _ = f.generate()
        h = "".join(e.event_id for e in events)
        hashes.add(h)
    assert len(hashes) == 2


def test_factory_includes_mail_events():
    f = WorkHistoryFactory(seed=7, days=30)
    events, _ = f.generate()
    types = {e.event_type for e in events}
    assert "mail_received" in types
    assert "mail_sent" in types


def test_factory_includes_meeting_events():
    f = WorkHistoryFactory(seed=3, days=60)
    events, _ = f.generate()
    types = {e.event_type for e in events}
    assert "meeting_scheduled" in types or "meeting_held" in types


def test_factory_planted_commitments():
    f = WorkHistoryFactory(seed=5, days=30)
    events, manifest = f.generate()
    assert manifest.planted_commitments >= 2
    planted = [p for p in f.planted_items() if p.kind == "commitment"]
    assert len(planted) == manifest.planted_commitments
    for p in planted:
        assert "owed_by" in p.data
        assert "due_date" in p.data
        assert "description" in p.data


def test_factory_planted_decisions():
    f = WorkHistoryFactory(seed=11, days=90)
    events, manifest = f.generate()
    assert manifest.planted_decisions >= 2
    decisions = [p for p in f.planted_items() if p.kind == "decision"]
    assert len(decisions) == manifest.planted_decisions
    for d in decisions:
        assert "title" in d.data
        assert "project" in d.data


def test_factory_planted_contradictions():
    f = WorkHistoryFactory(seed=13, days=120)
    events, manifest = f.generate()
    assert manifest.planted_contradictions >= 2
    contradictions = [p for p in f.planted_items() if p.kind == "contradiction"]
    assert len(contradictions) == manifest.planted_contradictions
    for c in contradictions:
        assert c.data["change"] == "due_date"
        assert "old_value" in c.data
        assert "new_value" in c.data


def test_factory_events_sorted_by_time():
    f = WorkHistoryFactory(seed=23, days=30)
    events, _ = f.generate()
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)


def test_factory_events_have_ids():
    f = WorkHistoryFactory(seed=1, days=5)
    events, _ = f.generate()
    for i, ev in enumerate(events):
        assert ev.event_id.startswith("evt-")
        assert ev.event_id == f"evt-{i:06d}"


def test_factory_manifest_has_checksum():
    f = WorkHistoryFactory(seed=1, days=10)
    events, manifest = f.generate()
    assert manifest.checksum != ""
    assert len(manifest.checksum) == 16  # first 16 chars of sha256 hex


def test_factory_custom_personas():
    f = WorkHistoryFactory(seed=1, days=7)
    f.add_persona(Persona("custom-1", "Dev", PersonaRole.ENGINEER, projects=["proj-x"]))
    events, manifest = f.generate()
    assert "custom-1" in manifest.personas
    # All events should reference custom-1
    persona_ids = {e.payload.get("persona_id") for e in events if "persona_id" in e.payload}
    assert "custom-1" in persona_ids


def test_factory_weekend_lighter():
    f = WorkHistoryFactory(seed=8, days=14)
    events, _ = f.generate()
    weekday_count = 0
    weekend_count = 0
    for ev in events:
        dt = datetime.fromisoformat(ev.timestamp)
        if dt.weekday() >= 5:
            weekend_count += 1
        else:
            weekday_count += 1
    assert weekday_count > weekend_count


def test_synthetic_event_dataclass():
    ev = SyntheticEvent("e1", "mail", "2026-01-01T00:00:00+00:00", {"a": 1})
    assert ev.event_id == "e1"
    assert ev.event_type == "mail"
    assert ev.payload == {"a": 1}


def test_planted_item_dataclass():
    item = PlantedItem("i1", "commitment", {"desc": "x"})
    assert item.item_id == "i1"
    assert item.kind == "commitment"
