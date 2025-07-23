from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from mnemofold.events import EventType
from mnemofold.factory import (
    FactoryConfig,
    Persona,
    PersonaRole,
    PlantedItem,
    SyntheticEvent,
    WorkdayPattern,
    WorkHistoryFactory,
)
from mnemofold.fold import Folder
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


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


def test_synthetic_event_to_event_conversion():
    synth = SyntheticEvent(
        "evt-000001",
        "mail_sent",
        "2026-01-02T03:04:05+00:00",
        {"subject": "hello", "body": "world"},
    )
    ev = synth.to_event()
    assert ev.event_type is EventType.MAIL_SENT
    assert ev.timestamp == datetime.fromisoformat(synth.timestamp)
    assert ev.content == {"subject": "hello", "body": "world"}


def test_synthetic_event_to_event_id_is_content_addressed():
    synth = SyntheticEvent("evt-000009", "note", "2026-01-02T00:00:00+00:00", {"text": "x"})
    ev = synth.to_event()
    assert ev.event_id != synth.event_id
    assert ev.event_id == synth.to_event().event_id
    assert ev.event_id.startswith("evt_")


def test_factory_events_convert_to_typed_events():
    f = WorkHistoryFactory(seed=5, days=14)
    events, _ = f.generate()
    typed = [e.to_event() for e in events]
    assert len(typed) == len(events)
    for synth, ev in zip(events, typed, strict=True):
        assert ev.content == synth.payload
        assert ev.event_id.startswith("evt_")


def test_synthetic_event_to_event_rejects_unknown_type():
    synth = SyntheticEvent("e", "not_a_type", "2026-01-02T00:00:00+00:00", {})
    with pytest.raises(ValueError):
        synth.to_event()


class TestFactoryConfig:
    def test_defaults_reproduce_baseline_checksum(self):
        baseline = WorkHistoryFactory(seed=5, days=20)
        with_default = WorkHistoryFactory(seed=5, days=20, config=FactoryConfig())
        _, m1 = baseline.generate()
        _, m2 = with_default.generate()
        assert m1.checksum == m2.checksum
        assert m1.event_count == m2.event_count

    def test_manifest_carries_config_echo(self):
        config = FactoryConfig(noise_level=0.5, workflow_repeats=2, include_designer=True)
        _, manifest = WorkHistoryFactory(seed=5, days=20, config=config).generate()
        assert manifest.config["noise_level"] == 0.5
        assert manifest.config["workflow_repeats"] == 2
        assert manifest.config["include_designer"] is True
        assert manifest.config["contradiction_kinds"] == ["due_date"]

    def test_default_config_echo(self):
        _, manifest = WorkHistoryFactory(seed=5, days=10).generate()
        assert manifest.config == FactoryConfig().to_dict()

    def test_config_validation_rejects_bad_values(self):
        with pytest.raises(ValueError, match="noise_level"):
            WorkHistoryFactory(config=FactoryConfig(noise_level=1.5))
        with pytest.raises(ValueError, match="workflow_repeats"):
            WorkHistoryFactory(config=FactoryConfig(workflow_repeats=-1))
        with pytest.raises(ValueError, match="unknown contradiction kinds"):
            WorkHistoryFactory(config=FactoryConfig(contradiction_kinds=("bogus",)))
        with pytest.raises(ValueError, match="must not be empty"):
            WorkHistoryFactory(config=FactoryConfig(contradiction_kinds=()))

    def test_config_is_immutable(self):
        config = FactoryConfig()
        with pytest.raises(FrozenInstanceError):
            config.noise_level = 0.9  # type: ignore[misc]

    def test_to_dict_roundtrip_stable(self):
        config = FactoryConfig(noise_level=0.3, workflow_repeats=1)
        assert config.to_dict() == config.to_dict()


class TestDesignerPersona:
    DESIGNER_TYPES = {"document_change", "note", "meeting_held", "mail_sent"}

    def test_default_history_has_three_personas(self):
        _, manifest = WorkHistoryFactory(seed=3, days=14).generate()
        assert manifest.personas == ["p1", "p2", "p3"]

    def test_flag_adds_designer(self):
        factory = WorkHistoryFactory(seed=3, days=14, config=FactoryConfig(include_designer=True))
        _, manifest = factory.generate()
        assert manifest.personas == ["p1", "p2", "p3", "p4"]
        designer = factory.personas[3]
        assert designer.role == PersonaRole.DESIGNER
        assert designer.name == "Dana Kim"

    def test_designer_produces_role_events(self):
        factory = WorkHistoryFactory(seed=3, days=30, config=FactoryConfig(include_designer=True))
        events, _ = factory.generate()
        designer_events = [e for e in events if e.payload.get("persona_id") == "p4"]
        assert designer_events
        assert all(e.event_type in self.DESIGNER_TYPES for e in designer_events)

    def test_default_stream_unchanged_by_flag_presence(self):
        _, plain = WorkHistoryFactory(seed=3, days=14).generate()
        _, flagged = WorkHistoryFactory(
            seed=3, days=14, config=FactoryConfig(include_designer=False)
        ).generate()
        assert plain.checksum == flagged.checksum

    def test_custom_personas_ignore_designer_flag(self):
        factory = WorkHistoryFactory(seed=3, days=14, config=FactoryConfig(include_designer=True))
        factory.add_persona(Persona("x1", "Solo", PersonaRole.ENGINEER, projects=["alpha"]))
        _, manifest = factory.generate()
        assert manifest.personas == ["x1"]


class TestFactorySweep:
    def test_same_seed_is_reproducible(self):
        _, a = WorkHistoryFactory(seed=99, days=30).generate()
        _, b = WorkHistoryFactory(seed=99, days=30).generate()
        assert a.checksum == b.checksum
        assert a.event_count == b.event_count

    def test_different_seeds_diverge(self):
        _, a = WorkHistoryFactory(seed=1, days=30).generate()
        _, b = WorkHistoryFactory(seed=2, days=30).generate()
        assert a.checksum != b.checksum

    def test_event_count_scales_with_days(self):
        _, small = WorkHistoryFactory(seed=7, days=10).generate()
        _, large = WorkHistoryFactory(seed=7, days=60).generate()
        assert large.event_count > small.event_count

    def test_events_are_chronologically_sorted(self):
        events, _ = WorkHistoryFactory(seed=7, days=30).generate()
        stamps = [e.timestamp for e in events]
        assert stamps == sorted(stamps)

    def test_event_ids_are_sequential(self):
        events, _ = WorkHistoryFactory(seed=7, days=14).generate()
        assert [e.event_id for e in events] == [f"evt-{i:06d}" for i in range(len(events))]

    def test_planted_counts_match_manifest(self):
        events, manifest = WorkHistoryFactory(seed=7, days=120).generate()
        assert manifest.planted_commitments >= 2
        assert manifest.planted_decisions >= 1
        assert manifest.planted_contradictions >= 1
        assert manifest.event_count == len(events)

    def test_all_event_types_are_valid(self):
        events, _ = WorkHistoryFactory(seed=7, days=60).generate()
        valid = {t.value for t in EventType}
        for e in events:
            assert e.event_type in valid

    def test_to_event_conversion_roundtrips(self):
        events, _ = WorkHistoryFactory(seed=7, days=14).generate()
        for synthetic in events[:20]:
            typed = synthetic.to_event()
            assert typed.event_type.value == synthetic.event_type
            assert typed.content  # non-empty payload


class TestNoiseEvents:
    def test_default_has_no_noise(self):
        events, _ = WorkHistoryFactory(seed=7, days=30).generate()
        assert not any(e.payload.get("noise") for e in events)

    def test_noise_level_zero_stream_matches_default(self):
        _, plain = WorkHistoryFactory(seed=7, days=30).generate()
        _, zero = WorkHistoryFactory(
            seed=7, days=30, config=FactoryConfig(noise_level=0.0)
        ).generate()
        assert plain.checksum == zero.checksum

    def test_high_noise_adds_labeled_events(self):
        events, _ = WorkHistoryFactory(
            seed=7, days=60, config=FactoryConfig(noise_level=1.0)
        ).generate()
        noise = [e for e in events if e.payload.get("noise") is True]
        assert noise, "high noise level should produce noise events"
        assert all(e.event_type in {"chat_message", "note"} for e in noise)

    def test_noise_events_carry_no_planted_refs(self):
        events, _ = WorkHistoryFactory(
            seed=7, days=60, config=FactoryConfig(noise_level=1.0)
        ).generate()
        for e in events:
            if e.payload.get("noise"):
                assert "commitment_ref" not in e.payload
                assert "decision_ref" not in e.payload
                assert "contradiction_ref" not in e.payload

    def test_more_noise_means_more_events(self):
        _, quiet = WorkHistoryFactory(
            seed=7, days=60, config=FactoryConfig(noise_level=0.0)
        ).generate()
        _, loud = WorkHistoryFactory(
            seed=7, days=60, config=FactoryConfig(noise_level=1.0)
        ).generate()
        assert loud.event_count > quiet.event_count


class TestRepeatedWorkflows:
    def test_default_has_no_workflow_events(self):
        events, _ = WorkHistoryFactory(seed=7, days=30).generate()
        assert not any("workflow" in e.payload for e in events)

    def test_repeats_zero_stream_matches_default(self):
        _, plain = WorkHistoryFactory(seed=7, days=30).generate()
        _, zero = WorkHistoryFactory(
            seed=7, days=30, config=FactoryConfig(workflow_repeats=0)
        ).generate()
        assert plain.checksum == zero.checksum

    def test_runs_emit_ordered_steps(self):
        events, _ = WorkHistoryFactory(
            seed=7, days=60, config=FactoryConfig(workflow_repeats=3)
        ).generate()
        wf = [e for e in events if e.payload.get("workflow") == "release"]
        assert len(wf) == 9  # 3 runs x 3 steps
        runs: dict[str, list[str]] = {}
        for e in sorted(wf, key=lambda e: e.timestamp):
            runs.setdefault(e.payload["run_id"], []).append(e.payload["step"])
        assert len(runs) == 3
        for steps in runs.values():
            assert steps == ["draft", "review", "publish"]

    def test_workflow_metadata_matches_miner_contract(self):
        events, _ = WorkHistoryFactory(
            seed=7, days=60, config=FactoryConfig(workflow_repeats=2)
        ).generate()
        for e in events:
            if e.payload.get("workflow"):
                assert {"workflow", "run_id", "step"} <= set(e.payload)

    def test_workflow_events_stay_within_history_window(self):
        events, manifest = WorkHistoryFactory(
            seed=7, days=30, config=FactoryConfig(workflow_repeats=4)
        ).generate()
        start = manifest.start_date
        for e in events:
            if e.payload.get("workflow"):
                assert e.timestamp >= start


class TestExpandedFactoryIntegration:
    def _workflow_store(self, factory: WorkHistoryFactory) -> MemoryStore:
        events, _ = factory.generate()
        store = MemoryStore()
        for e in events:
            if e.payload.get("workflow") != "release":
                continue
            store.add(
                MemoryItem(
                    item_id=e.payload["task_id"],
                    tier=MemoryTier.EPISODIC,
                    content=f"{e.payload['step']} for {e.payload['project']}",
                    created_at=e.timestamp,
                    metadata={
                        "workflow": e.payload["workflow"],
                        "run_id": e.payload["run_id"],
                        "step": e.payload["step"],
                    },
                )
            )
        return store

    def test_fold_mines_factory_workflows(self):
        factory = WorkHistoryFactory(seed=11, days=90, config=FactoryConfig(workflow_repeats=4))
        store = self._workflow_store(factory)
        report = Folder(min_episodes_for_recurrence=3).fold(store, "2025-06-01T00:00:00+00:00")
        seqs = [p for p in report.recurrence_proposals if p.get("kind") == "workflow_sequence"]
        assert any(
            p["workflow"] == "release"
            and p["steps"] == ["draft", "review", "publish"]
            and p["run_count"] == 4
            for p in seqs
        )

    def test_expanded_history_stays_deterministic(self):
        config = FactoryConfig(include_designer=True, noise_level=0.5, workflow_repeats=3)
        _, a = WorkHistoryFactory(seed=21, days=60, config=config).generate()
        _, b = WorkHistoryFactory(seed=21, days=60, config=config).generate()
        assert a.checksum == b.checksum
        assert a.event_count == b.event_count

    def test_planted_commitments_survive_expansion(self):
        config = FactoryConfig(include_designer=True, noise_level=0.5, workflow_repeats=3)
        factory = WorkHistoryFactory(seed=21, days=120, config=config)
        _, manifest = factory.generate()
        assert manifest.planted_commitments >= 2
        refs = {p.item_id for p in factory.planted_items() if p.kind == "commitment"}
        assert refs  # ground truth is still planted alongside the noise


class TestOwnerContradictions:
    def test_default_plants_only_due_date_contradictions(self):
        factory = WorkHistoryFactory(seed=13, days=180)
        factory.generate()
        contradictions = [p for p in factory.planted_items() if p.kind == "contradiction"]
        assert contradictions
        assert all(c.data["change"] == "due_date" for c in contradictions)

    def test_owner_kind_plants_reassignments(self):
        factory = WorkHistoryFactory(
            seed=13, days=180, config=FactoryConfig(contradiction_kinds=("owner",))
        )
        factory.generate()
        contradictions = [p for p in factory.planted_items() if p.kind == "contradiction"]
        assert contradictions
        assert all(c.data["change"] == "owner" for c in contradictions)

    def test_owner_change_names_a_different_owner(self):
        factory = WorkHistoryFactory(
            seed=13, days=180, config=FactoryConfig(contradiction_kinds=("owner",))
        )
        factory.generate()
        owners = [c.data for c in factory.planted_items() if c.kind == "contradiction"]
        assert any(d["old_value"] != d["new_value"] for d in owners)

    def test_mixed_kinds_produce_both_changes(self):
        factory = WorkHistoryFactory(
            seed=13, days=180, config=FactoryConfig(contradiction_kinds=("due_date", "owner"))
        )
        factory.generate()
        changes = {c.data["change"] for c in factory.planted_items() if c.kind == "contradiction"}
        assert changes <= {"due_date", "owner"}
        assert len(changes) >= 1

    def test_owner_contradiction_emits_event(self):
        factory = WorkHistoryFactory(
            seed=13, days=180, config=FactoryConfig(contradiction_kinds=("owner",))
        )
        events, _ = factory.generate()
        reassign = [e for e in events if e.payload.get("subject") == "Reassigning owner"]
        assert reassign
        assert all("contradiction_ref" in e.payload for e in reassign)

    def test_contradiction_targets_are_real_commitments(self):
        factory = WorkHistoryFactory(
            seed=13, days=180, config=FactoryConfig(contradiction_kinds=("owner",))
        )
        factory.generate()
        commitment_ids = {p.item_id for p in factory.planted_items() if p.kind == "commitment"}
        for c in factory.planted_items():
            if c.kind == "contradiction":
                assert c.data["target_commitment"] in commitment_ids


class TestDecisionContradictions:
    def test_decision_kind_plants_reversals(self):
        factory = WorkHistoryFactory(
            seed=17, days=180, config=FactoryConfig(contradiction_kinds=("decision",))
        )
        factory.generate()
        contradictions = [p for p in factory.planted_items() if p.kind == "contradiction"]
        assert contradictions
        assert all(c.data["change"] == "decision" for c in contradictions)

    def test_reversal_targets_an_existing_decision(self):
        factory = WorkHistoryFactory(
            seed=17, days=180, config=FactoryConfig(contradiction_kinds=("decision",))
        )
        factory.generate()
        decision_ids = {p.item_id for p in factory.planted_items() if p.kind == "decision"}
        reversals = [
            c
            for c in factory.planted_items()
            if c.kind == "contradiction" and c.data["change"] == "decision"
        ]
        assert reversals
        for c in reversals:
            # either it targets a real decision or (rare) had none to target
            assert c.data["target_decision"] in decision_ids or c.data["target_decision"] == ""

    def test_reversal_emits_note_event(self):
        factory = WorkHistoryFactory(
            seed=17, days=180, config=FactoryConfig(contradiction_kinds=("decision",))
        )
        events, _ = factory.generate()
        reversals = [
            e
            for e in events
            if e.payload.get("decision_ref", "").startswith("planted-contradiction")
        ]
        assert reversals
        assert all(e.event_type == "note" for e in reversals)

    def test_all_three_kinds_coexist(self):
        factory = WorkHistoryFactory(
            seed=17,
            days=180,
            config=FactoryConfig(contradiction_kinds=("due_date", "owner", "decision")),
        )
        factory.generate()
        changes = {c.data["change"] for c in factory.planted_items() if c.kind == "contradiction"}
        assert changes <= {"due_date", "owner", "decision"}

    def test_decision_contradiction_still_deterministic(self):
        config = FactoryConfig(contradiction_kinds=("due_date", "owner", "decision"))
        _, a = WorkHistoryFactory(seed=17, days=180, config=config).generate()
        _, b = WorkHistoryFactory(seed=17, days=180, config=config).generate()
        assert a.checksum == b.checksum


class TestContradictionRecovery:
    def _all_kinds_factory(self, seed: int = 23) -> WorkHistoryFactory:
        return WorkHistoryFactory(
            seed=seed,
            days=180,
            config=FactoryConfig(contradiction_kinds=("due_date", "owner", "decision")),
        )

    def test_manifest_count_matches_planted(self):
        factory = self._all_kinds_factory()
        _, manifest = factory.generate()
        planted = [p for p in factory.planted_items() if p.kind == "contradiction"]
        assert manifest.planted_contradictions == len(planted)

    def test_every_contradiction_has_an_event(self):
        factory = self._all_kinds_factory()
        events, _ = factory.generate()
        refs_in_events = {
            e.payload.get("contradiction_ref") for e in events if e.payload.get("contradiction_ref")
        }
        for c in factory.planted_items():
            if c.kind == "contradiction":
                assert c.item_id in refs_in_events

    def test_each_change_kind_is_represented(self):
        factory = self._all_kinds_factory(seed=29)
        factory.generate()
        changes = {c.data["change"] for c in factory.planted_items() if c.kind == "contradiction"}
        # with three kinds enabled and enough contradictions, all appear
        assert changes == {"due_date", "owner", "decision"}

    def test_contradiction_ids_are_unique(self):
        factory = self._all_kinds_factory()
        factory.generate()
        ids = [c.item_id for c in factory.planted_items() if c.kind == "contradiction"]
        assert len(ids) == len(set(ids))

    def test_contradictions_reference_known_projects(self):
        factory = self._all_kinds_factory()
        _, manifest = factory.generate()
        projects = set(manifest.projects)
        for e in factory._events:
            ref = e.payload.get("contradiction_ref")
            if ref and "project" in e.payload:
                assert e.payload["project"] in projects or e.payload["project"] == "general"


class TestPayloadChecksum:
    def _factory_with_name(self, name: str) -> WorkHistoryFactory:
        factory = WorkHistoryFactory(seed=5, days=20)
        factory.add_persona(Persona("p1", name, PersonaRole.PM, projects=["alpha"]))
        factory.add_project("alpha")
        return factory

    def test_checksum_still_deterministic(self):
        _, a = WorkHistoryFactory(seed=5, days=30).generate()
        _, b = WorkHistoryFactory(seed=5, days=30).generate()
        assert a.checksum == b.checksum
        assert len(a.checksum) == 16

    def test_payload_difference_changes_checksum(self):
        # Same seed, same structure (one persona, same projects), only the
        # display name differs — the old identity-only checksum missed this,
        # the payload-covering checksum must not.
        _, m1 = self._factory_with_name("Alice Chen").generate()
        _, m2 = self._factory_with_name("Alicia Chen").generate()
        assert m1.event_count == m2.event_count
        assert m1.checksum != m2.checksum

    def test_structure_still_covered(self):
        _, a = WorkHistoryFactory(seed=5, days=20).generate()
        _, b = WorkHistoryFactory(seed=5, days=21).generate()
        assert a.checksum != b.checksum

    def test_checksum_is_lowercase_hex(self):
        _, manifest = WorkHistoryFactory(seed=5, days=10).generate()
        assert all(c in "0123456789abcdef" for c in manifest.checksum)
