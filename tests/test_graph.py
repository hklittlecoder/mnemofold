"""Tests for the workstream graph module."""

from __future__ import annotations

import pytest

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    edge_checksum,
    node_checksum,
)


def make_person(uid: str, name: str) -> Node:
    return Node(node_id=uid, node_type=NodeType.PERSON, label=name)


def make_project(pid: str, name: str) -> Node:
    return Node(node_id=pid, node_type=NodeType.PROJECT, label=name)


class TestNodeTypes:
    def test_node_type_values_distinct(self):
        vals = [n.value for n in NodeType]
        assert len(vals) == len(set(vals))

    def test_edge_type_values_distinct(self):
        vals = [e.value for e in EdgeType]
        assert len(vals) == len(set(vals))

    def test_node_type_from_string(self):
        n = Node("n1", "person", "Alice")
        assert n.node_type == NodeType.PERSON


class TestGraphBasics:
    def test_empty_graph(self):
        g = WorkstreamGraph()
        assert g.node_count() == 0
        assert g.edge_count() == 0

    def test_add_node(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "Alice"))
        assert g.node_count() == 1
        assert g.get_node("p1") is not None
        assert g.get_node("p1").label == "Alice"

    def test_add_node_idempotent(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "Alice"))
        g.add_node(make_person("p1", "Alice"))
        assert g.node_count() == 1

    def test_get_missing_node(self):
        g = WorkstreamGraph()
        assert g.get_node("nope") is None

    def test_add_edge(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "Alice"))
        g.add_node(make_project("proj1", "Mnemofold"))
        g.add_edge(
            Edge(
                edge_id="e1",
                edge_type=EdgeType.OWNS,
                source_id="p1",
                target_id="proj1",
            )
        )
        assert g.edge_count() == 1
        assert len(g.outgoing_edges("p1")) == 1
        assert len(g.incoming_edges("proj1")) == 1

    def test_add_edge_missing_source_raises(self):
        g = WorkstreamGraph()
        g.add_node(make_project("proj1", "X"))
        with pytest.raises(ValueError, match="source node not found"):
            g.add_edge(Edge("e1", EdgeType.OWNS, "missing", "proj1"))

    def test_add_edge_missing_target_raises(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "A"))
        with pytest.raises(ValueError, match="target node not found"):
            g.add_edge(Edge("e1", EdgeType.OWNS, "p1", "missing"))

    def test_neighbors(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "Alice"))
        g.add_node(make_person("p2", "Bob"))
        g.add_node(make_project("proj1", "Mnemofold"))
        g.add_edge(Edge("e1", EdgeType.PARTICIPATES, "p1", "proj1"))
        g.add_edge(Edge("e2", EdgeType.PARTICIPATES, "p2", "proj1"))
        neighbors = g.neighbors("p1")
        assert len(neighbors) == 1
        assert neighbors[0].node_id == "proj1"

    def test_nodes_by_type(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "A"))
        g.add_node(make_person("p2", "B"))
        g.add_node(make_project("proj1", "P"))
        persons = g.nodes_by_type(NodeType.PERSON)
        assert len(persons) == 2
        projects = g.nodes_by_type(NodeType.PROJECT)
        assert len(projects) == 1


class TestChecksums:
    def test_node_checksum_deterministic(self):
        n1 = Node("n1", NodeType.PERSON, "Alice", {"email": "a@x.com"})
        n2 = Node("n1", NodeType.PERSON, "Alice", {"email": "a@x.com"})
        assert node_checksum(n1) == node_checksum(n2)

    def test_node_checksum_changes_with_label(self):
        n1 = Node("n1", NodeType.PERSON, "Alice")
        n2 = Node("n1", NodeType.PERSON, "Bob")
        assert node_checksum(n1) != node_checksum(n2)

    def test_edge_checksum_deterministic(self):
        e1 = Edge("e1", EdgeType.OWNS, "a", "b", {"since": "2024"})
        e2 = Edge("e1", EdgeType.OWNS, "a", "b", {"since": "2024"})
        assert edge_checksum(e1) == edge_checksum(e2)


class TestSerialization:
    def test_node_roundtrip(self):
        n = Node("n1", NodeType.PERSON, "Alice", {"role": "eng"})
        d = n.to_dict()
        n2 = Node.from_dict(d)
        assert n2.node_id == n.node_id
        assert n2.node_type == n.node_type
        assert n2.label == n.label
        assert n2.properties == n.properties

    def test_edge_roundtrip(self):
        e = Edge("e1", EdgeType.OWNS, "a", "b", {"since": "2024"})
        d = e.to_dict()
        e2 = Edge.from_dict(d)
        assert e2.edge_id == e.edge_id
        assert e2.edge_type == e.edge_type
        assert e2.source_id == e.source_id
        assert e2.target_id == e.target_id
        assert e2.properties == e.properties

    def test_graph_roundtrip(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "Alice"))
        g.add_node(make_project("proj1", "Mnemofold"))
        g.add_edge(Edge("e1", EdgeType.OWNS, "p1", "proj1", {"since": "day1"}))
        d = g.to_dict()
        g2 = WorkstreamGraph.from_dict(d)
        assert g2.node_count() == g.node_count()
        assert g2.edge_count() == g.edge_count()
        assert g2.get_node("p1").label == "Alice"
        assert len(g2.outgoing_edges("p1")) == 1

    def test_graph_serialization_deterministic(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p2", "Bob"))
        g.add_node(make_person("p1", "Alice"))
        g.add_node(make_project("proj1", "Mnemofold"))
        g.add_edge(Edge("e2", EdgeType.PARTICIPATES, "p2", "proj1"))
        g.add_edge(Edge("e1", EdgeType.OWNS, "p1", "proj1"))
        import json

        s1 = json.dumps(g.to_dict(), sort_keys=True)
        s2 = json.dumps(g.to_dict(), sort_keys=True)
        assert s1 == s2


class TestInvariants:
    def test_no_dangling_edges_in_clean_graph(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "A"))
        g.add_node(make_project("proj1", "P"))
        g.add_edge(Edge("e1", EdgeType.OWNS, "p1", "proj1"))
        assert g.check_no_dangling_edges() == []

    def test_provenance_acyclic_on_linear_chain(self):
        g = WorkstreamGraph()
        g.add_node(Node("d1", NodeType.DOCUMENT, "Doc v1"))
        g.add_node(Node("d2", NodeType.DOCUMENT, "Doc v2"))
        g.add_node(Node("d3", NodeType.DOCUMENT, "Doc v3"))
        g.add_edge(Edge("e1", EdgeType.DERIVED_FROM, "d2", "d1"))
        g.add_edge(Edge("e2", EdgeType.DERIVED_FROM, "d3", "d2"))
        assert g.check_provenance_acyclic() is True

    def test_deactivate_node_removes_edges(self):
        g = WorkstreamGraph()
        g.add_node(make_person("p1", "Alice"))
        g.add_node(make_project("proj1", "Mnemofold"))
        g.add_edge(Edge("e1", EdgeType.OWNS, "p1", "proj1"))
        assert g.edge_count() == 1
        g.deactivate_node("p1")
        assert g.get_node("p1") is None
        assert g.edge_count() == 0


class TestGraphSerializationGolden:
    def _sample(self) -> WorkstreamGraph:
        graph = WorkstreamGraph()
        graph.add_node(Node("n1", NodeType.PROJECT, "alpha"))
        graph.add_node(Node("n2", NodeType.PERSON, "Ana"))
        graph.add_edge(Edge("e1", EdgeType.OWNS, "n2", "n1"))
        return graph

    def test_to_dict_is_pinned_literal(self):
        assert self._sample().to_dict() == {
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "project",
                    "label": "alpha",
                    "properties": {},
                    "active": True,
                },
                {
                    "node_id": "n2",
                    "node_type": "person",
                    "label": "Ana",
                    "properties": {},
                    "active": True,
                },
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "edge_type": "owns",
                    "source_id": "n2",
                    "target_id": "n1",
                    "properties": {},
                    "active": True,
                }
            ],
        }

    def test_roundtrip_reserializes_identically(self):
        graph = self._sample()
        restored = WorkstreamGraph.from_dict(graph.to_dict())
        assert restored.to_dict() == graph.to_dict()
        assert restored.get_node("n1").to_dict() == graph.get_node("n1").to_dict()
