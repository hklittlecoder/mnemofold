"""Tests for inbox triage."""

from __future__ import annotations

import pytest

from mnemofold.graph import Edge, EdgeType, Node, NodeType, WorkstreamGraph
from mnemofold.triage import (
    TriageItem,
    TriagePriority,
    TriageResult,
    TriageScorer,
    attach_graph_importance,
    precision_at_k,
    sender_degrees,
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
