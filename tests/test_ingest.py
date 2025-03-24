"""Tests for ingestion: episode segmentation and entity resolution."""

from datetime import UTC, datetime, timedelta

from mnemofold.events import Event, EventType
from mnemofold.factory import WorkHistoryFactory
from mnemofold.ingest import (
    AliasTable,
    CommitmentExtractor,
    DecisionExtractor,
    Entity,
    EpisodeSegmenter,
)

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


class TestCommitmentExtractorPatterns:
    def _mail(self, body: str, sender: str = "alice") -> Event:
        return Event.mail_received(
            T0, sender=sender, subject="s", body=body, recipients=["bob"], thread_id="t"
        )

    def test_i_will_pattern(self):
        mentions = CommitmentExtractor().extract(self._mail("I will send the report by 2025-03-01"))
        assert len(mentions) == 1
        m = mentions[0]
        assert m.debtor == "alice"
        assert m.creditor == "bob"
        assert m.description == "send the report"
        assert m.due == "2025-03-01"
        assert m.confidence == 0.85

    def test_i_owe_you_uses_counterparty_as_creditor(self):
        body = "I owe you: Complete alpha milestone 0 by 2025-01-20."
        mentions = CommitmentExtractor().extract(self._mail(body))
        assert len(mentions) == 1
        assert mentions[0].creditor == "bob"
        assert mentions[0].description == "Complete alpha milestone 0"
        assert mentions[0].confidence == 0.95

    def test_i_owe_named_creditor(self):
        mentions = CommitmentExtractor().extract(self._mail("I owe carol: review PR by 2025-04-01"))
        assert len(mentions) == 1
        assert mentions[0].creditor == "carol"
        assert mentions[0].description == "review PR"

    def test_please_pattern_makes_recipient_the_debtor(self):
        mentions = CommitmentExtractor().extract(
            self._mail("Please submit timesheets by 2025-02-10")
        )
        assert len(mentions) == 1
        assert mentions[0].debtor == "bob"
        assert mentions[0].creditor == "alice"
        assert mentions[0].confidence == 0.7

    def test_action_item_task_uses_assignee_or_author(self):
        event = Event(
            EventType.MEETING_HELD,
            T0,
            {
                "title": "sync",
                "notes": "Action item: update risk log by 2025-05-01",
                "author": "carol",
                "attendees": ["carol", "dave"],
            },
        )
        mentions = CommitmentExtractor().extract(event)
        assert len(mentions) == 1
        assert mentions[0].debtor == "carol"
        assert mentions[0].description == "update risk log"
        assert mentions[0].due == "2025-05-01"

    def test_action_item_without_due_keeps_due_none(self):
        event = Event(EventType.NOTE, T0, {"text": "Action item: rotate the on-call schedule"})
        mentions = CommitmentExtractor().extract(event)
        assert len(mentions) == 1
        assert mentions[0].due is None

    def test_plain_text_yields_no_mentions(self):
        assert CommitmentExtractor().extract(self._mail("Lunch was great, thanks!")) == []


class TestCommitmentExtractorEvidence:
    def test_span_quote_matches_source_slice_both_ways(self):
        event = Event.mail_received(
            T0,
            sender="alice",
            subject="s",
            body="heads up: I will ship the parser by 2025-06-01 ok?",
            recipients=["bob"],
            thread_id="t",
        )
        m = CommitmentExtractor().extract(event)[0]
        assert m.evidence.field == "body"
        assert event.content["body"][m.evidence.start : m.evidence.end] == m.evidence.quote
        assert m.evidence.resolves_in(event)

    def test_span_does_not_resolve_in_other_event(self):
        e1 = Event.mail_received(
            T0, sender="a", subject="s", body="I will ship by 2025-06-01", recipients=["b"]
        )
        e2 = Event.mail_received(
            T0, sender="a", subject="s", body="totally different text", recipients=["b"]
        )
        m = CommitmentExtractor().extract(e1)[0]
        assert not m.evidence.resolves_in(e2)


class TestCommitmentExtractorStructured:
    def _planted_style(self) -> Event:
        return Event(
            EventType.MAIL_SENT,
            T0,
            {
                "persona_id": "p1",
                "from": "p1@co.example",
                "subject": "Commitment: Complete alpha milestone 0",
                "body": "I owe you: Complete alpha milestone 0 by 2025-01-20T00:00:00+00:00.",
                "commitment_ref": "planted-commitment-0",
                "project": "alpha",
            },
        )

    def test_structured_ref_dedupes_to_full_confidence(self):
        mentions = CommitmentExtractor().extract(self._planted_style())
        assert len(mentions) == 1
        m = mentions[0]
        assert m.confidence == 1.0
        assert m.description == "Complete alpha milestone 0"
        assert m.due == "2025-01-20"
        assert m.debtor == "p1"
        assert m.evidence.field == "commitment_ref"
        assert m.evidence.resolves_in(self._planted_style())

    def test_deadline_update_mail_is_not_a_commitment(self):
        event = Event(
            EventType.MAIL_SENT,
            T0,
            {
                "from": "p1@co.example",
                "subject": "Updating deadline",
                "body": "New deadline: 2025-03-11",
                "commitment_ref": "planted-commitment-0",
            },
        )
        assert CommitmentExtractor().extract(event) == []

    def test_commitment_ack_uses_description_field(self):
        event = Event(
            EventType.COMMITMENT_ACK,
            T0,
            {"commitment_ref": "c1", "description": "ship beta", "persona_id": "p2"},
        )
        mentions = CommitmentExtractor().extract(event)
        assert len(mentions) == 1
        assert mentions[0].description == "ship beta"
        assert mentions[0].confidence == 1.0
        assert mentions[0].debtor == "p2"

    def test_min_confidence_filters_weak_patterns(self):
        event = Event.mail_received(
            T0,
            sender="a",
            subject="s",
            body="Please review by 2025-01-01. I will merge after that by 2025-01-02.",
            recipients=["b"],
        )
        assert len(CommitmentExtractor(min_confidence=0.75).extract(event)) == 1


class TestCommitmentExtractorOnFactory:
    def test_recovers_all_planted_commitments(self):
        factory = WorkHistoryFactory(seed=42, days=60)
        events, manifest = factory.generate()
        assert manifest.planted_commitments >= 2
        typed = [ev.to_event() for ev in events]
        by_ref: dict[str, Event] = {}
        for ev in typed:
            ref = ev.content.get("commitment_ref")
            subject = str(ev.content.get("subject", ""))
            if isinstance(ref, str) and subject.startswith("Commitment:"):
                by_ref[ref] = ev
        extractor = CommitmentExtractor()
        planted = [p for p in factory.planted_items() if p.kind == "commitment"]
        for p in planted:
            ev = by_ref[p.item_id]
            matches = [
                m
                for m in extractor.extract(ev)
                if m.description == p.data["description"]
                and m.due == p.data["due_date"][:10]
                and m.confidence == 1.0
            ]
            assert matches, f"planted {p.item_id} not recovered"
            assert matches[0].evidence.resolves_in(ev)

    def test_extraction_is_deterministic(self):
        factory = WorkHistoryFactory(seed=7, days=30)
        events, _ = factory.generate()
        typed = [ev.to_event() for ev in events]
        first = CommitmentExtractor().extract_all(typed)
        second = CommitmentExtractor().extract_all(typed)
        key = lambda m: (m.debtor, m.creditor, m.description, m.due, m.confidence)  # noqa: E731
        assert [key(m) for m in first] == [key(m) for m in second]
        assert len(first) >= 2


class TestDecisionExtractor:
    def test_structured_decision_record(self):
        event = Event(
            EventType.NOTE,
            T0,
            {
                "title": "Decision record: alpha",
                "content": "Decision made about alpha.",
                "decision_ref": "planted-decision-0",
                "project": "alpha",
            },
        )
        mentions = DecisionExtractor().extract(event)
        assert len(mentions) == 1
        m = mentions[0]
        assert m.confidence == 1.0
        assert m.project == "alpha"
        assert m.evidence.field == "decision_ref"
        assert m.evidence.resolves_in(event)

    def test_structured_requires_decision_title(self):
        event = Event(
            EventType.NOTE,
            T0,
            {"title": "Random note", "text": "hello", "decision_ref": "d1"},
        )
        assert DecisionExtractor().extract(event) == []

    def test_we_decided_to_pattern_with_rationale(self):
        event = Event(
            EventType.MAIL_SENT,
            T0,
            {
                "subject": "recap",
                "body": "We decided to postpone the launch because of budget cuts",
                "project": "beta",
            },
        )
        mentions = DecisionExtractor().extract(event)
        assert len(mentions) == 1
        assert mentions[0].title == "postpone the launch"
        assert mentions[0].rationale == "of budget cuts"
        assert mentions[0].project == "beta"
        assert mentions[0].confidence == 0.85

    def test_decision_colon_pattern(self):
        event = Event(EventType.NOTE, T0, {"text": "Decision: use postgres for the ledger"})
        mentions = DecisionExtractor().extract(event)
        assert len(mentions) == 1
        assert mentions[0].title == "use postgres for the ledger"
        assert mentions[0].confidence == 0.75

    def test_plain_text_yields_no_decisions(self):
        event = Event(EventType.NOTE, T0, {"text": "standup notes about weather"})
        assert DecisionExtractor().extract(event) == []

    def test_evidence_span_resolves_in_source(self):
        event = Event(
            EventType.CHAT_MESSAGE,
            T0,
            {"text": "btw we chose option B", "channel": "eng"},
        )
        mentions = DecisionExtractor().extract(event)
        assert len(mentions) == 1
        assert mentions[0].evidence.resolves_in(event)
        assert (
            event.content["text"][mentions[0].evidence.start : mentions[0].evidence.end]
            == mentions[0].evidence.quote
        )

    def test_recovers_all_planted_decisions_from_factory(self):
        factory = WorkHistoryFactory(seed=42, days=90)
        events, manifest = factory.generate()
        assert manifest.planted_decisions >= 2
        typed = [ev.to_event() for ev in events]
        by_ref: dict[str, Event] = {}
        for ev in typed:
            ref = ev.content.get("decision_ref")
            if isinstance(ref, str):
                by_ref[ref] = ev
        extractor = DecisionExtractor()
        planted = [p for p in factory.planted_items() if p.kind == "decision"]
        for p in planted:
            ev = by_ref[p.item_id]
            matches = [
                m
                for m in extractor.extract(ev)
                if m.project == p.data["project"] and m.confidence == 1.0
            ]
            assert matches, f"planted {p.item_id} not recovered"

    def test_min_confidence_filters_textual_mentions(self):
        event = Event(EventType.NOTE, T0, {"text": "Decision: pick a vendor later"})
        assert DecisionExtractor(min_confidence=0.8).extract(event) == []
        assert len(DecisionExtractor(min_confidence=0.7).extract(event)) == 1
