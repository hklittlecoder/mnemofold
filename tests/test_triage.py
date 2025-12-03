"""Tests for inbox triage."""

from __future__ import annotations

import pytest

from mnemofold.events import EventType
from mnemofold.factory import WorkHistoryFactory
from mnemofold.graph import Edge, EdgeType, Node, NodeType, WorkstreamGraph
from mnemofold.ingest import CommitmentExtractor
from mnemofold.triage import (
    BatchPlan,
    TriageBatcher,
    TriageItem,
    TriagePriority,
    TriageResult,
    TriageScorer,
    attach_graph_importance,
    group_by_priority,
    precision_at_k,
    sender_degrees,
    triage_summary,
)


class TestTriageScorer:
    def test_basic_score(self):
        scorer = TriageScorer()
        item = TriageItem(
            item_id="m1",
            title="Hello",
            sender="alice",
            received_at="2024-01-15T10:00:00+00:00",
        )
        result = scorer.score(item, "2024-01-15T12:00:00+00:00")
        assert 0.0 <= result.score <= 1.0
        assert result.priority in TriagePriority

    def test_deadline_increases_priority(self):
        scorer = TriageScorer()
        base = TriageItem(
            item_id="b",
            title="x",
            sender="a",
            received_at="2024-01-15T10:00:00+00:00",
        )
        with_deadline = TriageItem(
            item_id="d",
            title="x",
            sender="a",
            received_at="2024-01-15T10:00:00+00:00",
            has_deadline=True,
            deadline="2024-01-16T10:00:00+00:00",
        )
        now = "2024-01-15T12:00:00+00:00"
        assert scorer.score(with_deadline, now).score > scorer.score(base, now).score

    def test_overdue_deadline_max_priority(self):
        scorer = TriageScorer()
        item = TriageItem(
            item_id="m1",
            title="urgent",
            sender="boss",
            received_at="2024-01-10T00:00:00+00:00",
            has_deadline=True,
            deadline="2024-01-15T00:00:00+00:00",
            has_explicit_ask=True,
            mentions_commitment=True,
            sender_importance=0.9,
        )
        result = scorer.score(item, "2024-01-20T00:00:00+00:00")
        assert result.priority == TriagePriority.URGENT
        assert "deadline_proximity" in str(result.reasons)

    def test_explicit_ask_increases_score(self):
        scorer = TriageScorer()
        item_no = TriageItem("a", "t", "s", "2024-01-01T00:00:00+00:00")
        item_yes = TriageItem("b", "t", "s", "2024-01-01T00:00:00+00:00", has_explicit_ask=True)
        now = "2024-01-01T12:00:00+00:00"
        assert scorer.score(item_yes, now).score > scorer.score(item_no, now).score

    def test_sender_importance(self):
        scorer = TriageScorer()
        low = TriageItem("a", "t", "stranger", "2024-01-01T00:00:00+00:00", sender_importance=0.1)
        high = TriageItem("b", "t", "boss", "2024-01-01T00:00:00+00:00", sender_importance=0.9)
        now = "2024-01-01T12:00:00+00:00"
        assert scorer.score(high, now).score > scorer.score(low, now).score

    def test_commitment_mention(self):
        scorer = TriageScorer()
        no = TriageItem("a", "t", "s", "2024-01-01T00:00:00+00:00")
        yes = TriageItem("b", "t", "s", "2024-01-01T00:00:00+00:00", mentions_commitment=True)
        now = "2024-01-01T12:00:00+00:00"
        assert scorer.score(yes, now).score > scorer.score(no, now).score

    def test_batch_score_sorted(self):
        scorer = TriageScorer()
        items = [
            TriageItem(
                f"i{i}",
                f"t{i}",
                "sender",
                "2024-01-01T00:00:00+00:00",
                has_deadline=(i == 0),
                deadline="2024-01-02T00:00:00+00:00" if i == 0 else "",
                sender_importance=0.1 + i * 0.1,
            )
            for i in range(5)
        ]
        now = "2024-01-01T12:00:00+00:00"
        results = scorer.batch_score(items, now)
        assert len(results) == 5
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_quiet_hours_reduce_non_urgent(self):
        scorer = TriageScorer()
        results = [
            type(
                "R",
                (),
                {"item_id": "u", "score": 0.9, "priority": TriagePriority.URGENT, "reasons": []},
            )(),
            type(
                "R",
                (),
                {"item_id": "h", "score": 0.7, "priority": TriagePriority.HIGH, "reasons": []},
            )(),
            type(
                "R",
                (),
                {"item_id": "n", "score": 0.4, "priority": TriagePriority.NORMAL, "reasons": []},
            )(),
        ]
        # 10 PM is quiet hours
        modified = scorer.apply_quiet_hours(results, now="2024-01-15T22:00:00+00:00")
        assert modified[0].item_id == "u"  # urgent stays
        assert any("quiet_hours_reduced" in m.reasons for m in modified if m.item_id != "u")

    def test_reasons_are_informative(self):
        scorer = TriageScorer()
        item = TriageItem(
            "m1",
            "test",
            "alice",
            "2024-01-01T00:00:00+00:00",
            has_explicit_ask=True,
            has_deadline=True,
            deadline="2024-01-02T00:00:00+00:00",
            sender_importance=0.8,
        )
        result = scorer.score(item, "2024-01-01T12:00:00+00:00")
        assert len(result.reasons) >= 2


class TestPrecisionAtK:
    def test_perfect_precision(self):
        from mnemofold.triage import TriageResult

        results = [
            TriageResult("a", 0.9, TriagePriority.HIGH),
            TriageResult("b", 0.8, TriagePriority.HIGH),
            TriageResult("c", 0.7, TriagePriority.NORMAL),
        ]
        labels = {"a": True, "b": True, "c": False}
        assert precision_at_k(results, labels, 2) == 1.0

    def test_half_precision(self):
        from mnemofold.triage import TriageResult

        results = [
            TriageResult("a", 0.9, TriagePriority.HIGH),
            TriageResult("b", 0.8, TriagePriority.HIGH),
        ]
        labels = {"a": True, "b": False}
        assert precision_at_k(results, labels, 2) == 0.5

    def test_zero_k(self):

        assert precision_at_k([], {}, 0) == 0.0


class TestGroupByPriority:
    def test_all_priority_levels_present_even_when_empty(self):
        results = [
            TriageResult("a", 0.9, TriagePriority.HIGH),
            TriageResult("b", 0.3, TriagePriority.LOW),
        ]
        groups = group_by_priority(results)
        assert set(groups.keys()) == set(TriagePriority)
        assert len(groups[TriagePriority.HIGH]) == 1
        assert len(groups[TriagePriority.LOW]) == 1
        assert groups[TriagePriority.URGENT] == []

    def test_preserves_score_order_within_band(self):
        results = [
            TriageResult("a", 0.9, TriagePriority.HIGH),
            TriageResult("b", 0.85, TriagePriority.HIGH),
            TriageResult("c", 0.2, TriagePriority.LOW),
        ]
        groups = group_by_priority(results)
        assert [r.item_id for r in groups[TriagePriority.HIGH]] == ["a", "b"]

    def test_empty_input_produces_all_empty_bands(self):
        groups = group_by_priority([])
        assert all(len(v) == 0 for v in groups.values())


class TestTriageSummary:
    def test_total_and_by_priority_counts(self):
        results = [
            TriageResult("a", 0.95, TriagePriority.URGENT),
            TriageResult("b", 0.8, TriagePriority.HIGH),
            TriageResult("c", 0.5, TriagePriority.NORMAL),
            TriageResult("d", 0.2, TriagePriority.LOW),
        ]
        summary = triage_summary(results)
        assert summary["total"] == 4
        assert summary["by_priority"]["urgent"] == 1
        assert summary["by_priority"]["high"] == 1
        assert summary["by_priority"]["normal"] == 1
        assert summary["by_priority"]["low"] == 1
        assert summary["urgent_fraction"] == 0.25

    def test_empty_results_zero_fraction(self):
        summary = triage_summary([])
        assert summary["total"] == 0
        assert summary["urgent_fraction"] == 0.0


class TestQuietHoursReclassification:
    NIGHT = "2024-01-15T22:00:00+00:00"
    DAY = "2024-01-15T10:00:00+00:00"

    def _result(self, item_id: str, score: float, priority: TriagePriority) -> TriageResult:
        return TriageResult(item_id=item_id, score=score, priority=priority)

    def test_reduced_high_becomes_normal(self):
        modified = TriageScorer().apply_quiet_hours(
            [self._result("h", 0.7, TriagePriority.HIGH)], now=self.NIGHT
        )
        assert modified[0].score == pytest.approx(0.4)
        assert modified[0].priority == TriagePriority.NORMAL

    def test_reduced_normal_becomes_low(self):
        modified = TriageScorer().apply_quiet_hours(
            [self._result("n", 0.4, TriagePriority.NORMAL)], now=self.NIGHT
        )
        assert modified[0].priority == TriagePriority.LOW

    def test_urgent_passes_through_untouched(self):
        modified = TriageScorer().apply_quiet_hours(
            [self._result("u", 0.9, TriagePriority.URGENT)], now=self.NIGHT
        )
        assert modified[0].score == 0.9
        assert modified[0].priority == TriagePriority.URGENT
        assert modified[0].reasons == []

    def test_daytime_leaves_results_alone(self):
        modified = TriageScorer().apply_quiet_hours(
            [self._result("h", 0.7, TriagePriority.HIGH)], now=self.DAY
        )
        assert modified[0].priority == TriagePriority.HIGH
        assert modified[0].reasons == []

    def test_score_and_band_always_consistent_at_night(self):
        scorer = TriageScorer()
        results = [
            self._result("a", 0.95, TriagePriority.HIGH),
            self._result("b", 0.7, TriagePriority.HIGH),
            self._result("c", 0.62, TriagePriority.NORMAL),
            self._result("d", 0.3, TriagePriority.NORMAL),
        ]
        modified = scorer.apply_quiet_hours(results, now=self.NIGHT)
        for r in modified:
            assert r.priority == scorer._classify(r.score)
        assert modified[0].item_id == "a"  # re-sorted by reduced score


class TestGraphSenderImportance:
    def _graph(self) -> WorkstreamGraph:
        graph = WorkstreamGraph()
        graph.add_node(Node(node_id="alice", node_type=NodeType.PERSON, label="Alice"))
        graph.add_node(Node(node_id="bob", node_type=NodeType.PERSON, label="Bob"))
        graph.add_node(Node(node_id="carol", node_type=NodeType.PERSON, label="Carol"))
        graph.add_node(Node(node_id="p1", node_type=NodeType.PROJECT, label="P1"))
        graph.add_node(Node(node_id="p2", node_type=NodeType.PROJECT, label="P2"))
        graph.add_edge(
            Edge(edge_id="e1", edge_type=EdgeType.OWNS, source_id="alice", target_id="p1")
        )
        graph.add_edge(
            Edge(edge_id="e2", edge_type=EdgeType.OWNS, source_id="alice", target_id="p2")
        )
        graph.add_edge(
            Edge(
                edge_id="e3",
                edge_type=EdgeType.PARTICIPATES,
                source_id="alice",
                target_id="bob",
            )
        )
        graph.add_edge(Edge(edge_id="e4", edge_type=EdgeType.OWNS, source_id="bob", target_id="p1"))
        return graph

    def _item(self, sender: str) -> TriageItem:
        return TriageItem(
            item_id=f"m-{sender}",
            title="t",
            sender=sender,
            received_at="2025-03-10T09:00:00+00:00",
        )

    def test_degrees_count_both_directions(self):
        degrees = sender_degrees(self._graph())
        assert degrees["alice"] == 3
        assert degrees["bob"] == 2
        assert degrees["carol"] == 0

    def test_importance_is_relative_to_hub(self):
        items = [self._item("alice"), self._item("bob"), self._item("carol")]
        attach_graph_importance(items, self._graph())
        assert items[0].sender_importance == 1.0
        assert items[1].sender_importance == round(0.2 + 0.8 * 2 / 3, 6)
        assert items[2].sender_importance == 0.2

    def test_unknown_sender_keeps_default(self):
        items = [self._item("dave")]
        attach_graph_importance(items, self._graph())
        assert items[0].sender_importance == 0.5

    def test_empty_graph_changes_nothing(self):
        items = [self._item("alice")]
        attach_graph_importance(items, WorkstreamGraph())
        assert items[0].sender_importance == 0.5

    def test_deactivated_edges_do_not_count(self):
        graph = self._graph()
        graph.deactivate_edge("e1")
        degrees = sender_degrees(graph)
        assert degrees["alice"] == 2

    def test_hub_sender_scores_higher_end_to_end(self):
        items = [self._item("alice"), self._item("carol")]
        attach_graph_importance(items, self._graph())
        scorer = TriageScorer()
        results = scorer.batch_score(items, "2025-03-10T09:00:00+00:00")
        assert results[0].item_id == "m-alice"

    def test_importance_is_deterministic(self):
        first = [self._item("alice"), self._item("bob")]
        second = [self._item("alice"), self._item("bob")]
        attach_graph_importance(first, self._graph())
        attach_graph_importance(second, self._graph())
        assert [i.sender_importance for i in first] == [i.sender_importance for i in second]


class TestTriageBatcher:
    def _result(self, item_id: str, priority: TriagePriority, score: float = 0.5) -> TriageResult:
        return TriageResult(item_id=item_id, score=score, priority=priority)

    def test_buckets_by_priority(self):
        results = [
            self._result("u1", TriagePriority.URGENT, 0.9),
            self._result("h1", TriagePriority.HIGH, 0.7),
            self._result("n1", TriagePriority.NORMAL, 0.4),
            self._result("l1", TriagePriority.LOW, 0.1),
        ]
        plan: BatchPlan = TriageBatcher().batch(results)
        assert [r.item_id for r in plan.act_now] == ["u1"]
        assert [r.item_id for r in plan.review] == ["h1", "n1"]
        assert [r.item_id for r in plan.defer] == ["l1"]
        assert plan.total() == 4

    def test_urgent_overflow_moves_to_review_with_reason(self):
        results = [self._result(f"u{i}", TriagePriority.URGENT, 0.9 - i * 0.01) for i in range(5)]
        plan = TriageBatcher(max_act_now=3).batch(results)
        assert [r.item_id for r in plan.act_now] == ["u0", "u1", "u2"]
        assert [r.item_id for r in plan.review] == ["u3", "u4"]
        assert "batch_overflow" in plan.review[0].reasons
        assert plan.total() == 5

    def test_review_overflow_moves_to_defer(self):
        results = [self._result(f"n{i}", TriagePriority.NORMAL, 0.4) for i in range(4)]
        plan = TriageBatcher(max_review=2).batch(results)
        assert [r.item_id for r in plan.review] == ["n0", "n1"]
        assert [r.item_id for r in plan.defer] == ["n2", "n3"]
        assert all("batch_overflow" in r.reasons for r in plan.defer)

    def test_input_order_preserved_within_buckets(self):
        results = [
            self._result("b", TriagePriority.NORMAL, 0.5),
            self._result("a", TriagePriority.NORMAL, 0.45),
        ]
        plan = TriageBatcher().batch(results)
        assert [r.item_id for r in plan.review] == ["b", "a"]

    def test_empty_input_yields_empty_plan(self):
        plan = TriageBatcher().batch([])
        assert plan.total() == 0
        assert plan.act_now == []
        assert plan.review == []
        assert plan.defer == []

    def test_no_items_are_lost_under_tight_caps(self):
        results = (
            [self._result(f"u{i}", TriagePriority.URGENT, 0.9) for i in range(4)]
            + [self._result(f"h{i}", TriagePriority.HIGH, 0.7) for i in range(12)]
            + [self._result("low", TriagePriority.LOW, 0.1)]
        )
        plan = TriageBatcher(max_act_now=2, max_review=5).batch(results)
        assert plan.total() == len(results)
        assert len(plan.act_now) == 2
        assert len(plan.review) == 5


class TestPrecisionAtKOnFactory:
    """Measured triage quality on the synthetic factory corpus.

    Every number here comes from the seeded synthetic history (seed 9,
    30 days) with planted commitment mails as ground truth — not from a
    real corpus, a real inbox, or a live model. Commitment flags are
    derived by running the commitment extractor over event text, so the
    scorer is not fed the labels directly. Values are exact because all
    inputs are deterministic; they are pinned so scoring changes show up
    as deliberate diffs.
    """

    NOW = "2025-01-31T00:00:00+00:00"

    def _corpus(self):
        factory = WorkHistoryFactory(seed=9, days=30)
        events, _ = factory.generate()
        extractor = CommitmentExtractor()
        planted_refs = {p.item_id for p in factory.planted_items() if p.kind == "commitment"}
        items: list[TriageItem] = []
        labels: dict[str, bool] = {}
        for synthetic in events:
            event = synthetic.to_event()
            if event.event_type not in (
                EventType.MAIL_RECEIVED,
                EventType.MAIL_SENT,
                EventType.CHAT_MESSAGE,
            ):
                continue
            content = event.content
            mentions = extractor.extract(event)
            due = next((m.due for m in mentions if m.due), None)
            items.append(
                TriageItem(
                    item_id=event.event_id,
                    title=str(content.get("subject", content.get("channel", ""))),
                    sender=str(content.get("sender", content.get("persona_id", ""))),
                    received_at=event.timestamp.isoformat(),
                    content=str(content.get("body", content.get("text", ""))),
                    mentions_commitment=bool(mentions),
                    has_deadline=due is not None,
                    deadline=f"{due}T00:00:00+00:00" if due else "",
                )
            )
            ref = content.get("commitment_ref")
            labels[event.event_id] = isinstance(ref, str) and ref in planted_refs
        return items, labels

    def test_top_of_inbox_is_a_planted_commitment(self):
        items, labels = self._corpus()
        results = TriageScorer().batch_score(items, self.NOW)
        assert precision_at_k(results, labels, 1) == 1.0

    def test_precision_at_k_measured_on_synthetic_corpus(self):
        items, labels = self._corpus()
        k = sum(1 for value in labels.values() if value)
        assert k == 3  # this seed plants exactly three commitment mails
        results = TriageScorer().batch_score(items, self.NOW)
        # measured: two of the three planted mails land in the top three
        assert precision_at_k(results, labels, k) == round(2 / 3, 6)
        # measured: still two planted mails inside the top five
        assert precision_at_k(results, labels, 5) == round(2 / 5, 6)

    def test_reversed_ranking_scores_baseline_zero(self):
        items, labels = self._corpus()
        results = TriageScorer().batch_score(items, self.NOW)
        k = sum(1 for value in labels.values() if value)
        assert precision_at_k(list(reversed(results)), labels, k) == 0.0

    def test_ranking_is_deterministic(self):
        items, _ = self._corpus()
        first = [r.item_id for r in TriageScorer().batch_score(items, self.NOW)]
        second = [r.item_id for r in TriageScorer().batch_score(items, self.NOW)]
        assert first == second


class TestTriageEdges:
    def test_zero_weights_yield_low_priority(self):
        scorer = TriageScorer(
            deadline_weight=0.0,
            sender_weight=0.0,
            ask_weight=0.0,
            commitment_weight=0.0,
            staleness_weight=0.0,
            thread_weight=0.0,
        )
        item = TriageItem("x", "t", "s", "2024-01-01T00:00:00+00:00", has_explicit_ask=True)
        result = scorer.score(item, "2024-01-01T00:00:00+00:00")
        assert result.score == 0.0
        assert result.priority == TriagePriority.LOW

    def test_invalid_deadline_contributes_nothing(self):
        item = TriageItem(
            "x",
            "t",
            "s",
            "2024-01-01T00:00:00+00:00",
            has_deadline=True,
            deadline="not-a-date",
        )
        result = TriageScorer().score(item, "2024-01-01T00:00:00+00:00")
        assert not any("deadline_proximity" in reason for reason in result.reasons)

    def test_invalid_now_treats_deadline_as_absent(self):
        item = TriageItem(
            "x",
            "t",
            "s",
            "2024-01-01T00:00:00+00:00",
            has_deadline=True,
            deadline="2024-01-02T00:00:00+00:00",
        )
        result = TriageScorer().score(item, "garbage")
        assert not any("deadline_proximity" in reason for reason in result.reasons)

    def test_past_deadline_scores_maximum_proximity(self):
        item = TriageItem(
            "x",
            "t",
            "s",
            "2024-01-01T00:00:00+00:00",
            has_deadline=True,
            deadline="2023-12-01T00:00:00+00:00",
        )
        result = TriageScorer().score(item, "2024-01-01T00:00:00+00:00")
        assert any(reason.startswith("deadline_proximity=1.00") for reason in result.reasons)

    def test_precision_at_k_edges(self):
        results = [TriageResult("a", 0.9, TriagePriority.URGENT)]
        assert precision_at_k(results, {"a": True}, 0) == 0.0
        assert precision_at_k([], {"a": True}, 5) == 0.0
        assert precision_at_k(results, {"a": True}, 5) == 1.0
        assert precision_at_k(results, {}, 1) == 0.0

    def test_staleness_fresh_thread_scores_above_stale(self):
        fresh = TriageItem(
            "fresh", "t", "s", "2024-01-01T00:00:00+00:00", thread_staleness_hours=0.0
        )
        stale = TriageItem(
            "stale", "t", "s", "2024-01-01T00:00:00+00:00", thread_staleness_hours=96.0
        )
        scorer = TriageScorer()
        assert (
            scorer.score(fresh, "2024-01-01T00:00:00+00:00").score
            > scorer.score(stale, "2024-01-01T00:00:00+00:00").score
        )
