"""Supersede chains and contradiction pairs over versioned graphs."""

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    contradiction_pairs,
    supersede_chain,
)


def version_graph() -> WorkstreamGraph:
    g = WorkstreamGraph()
    for vid in ("v1", "v2", "v3"):
        g.add_node(Node(node_id=vid, node_type=NodeType.DECISION, label=vid))
    g.add_edge(Edge(edge_id="s1", edge_type=EdgeType.SUPERSEDES, source_id="v2", target_id="v1"))
    g.add_edge(Edge(edge_id="s2", edge_type=EdgeType.SUPERSEDES, source_id="v3", target_id="v2"))
    return g


class TestSupersedeChain:
    def test_chain_from_any_version(self):
        g = version_graph()
        for start in ("v1", "v2", "v3"):
            assert supersede_chain(g, start) == ["v3", "v2", "v1"]

    def test_unknown_node(self):
        assert supersede_chain(version_graph(), "ghost") == []

    def test_singleton_chain(self):
        g = WorkstreamGraph()
        g.add_node(Node(node_id="solo", node_type=NodeType.DECISION, label="solo"))
        assert supersede_chain(g, "solo") == ["solo"]

    def test_non_supersede_edges_ignored(self):
        g = version_graph()
        g.add_node(Node(node_id="ref", node_type=NodeType.DOCUMENT, label="ref"))
        g.add_edge(
            Edge(edge_id="r1", edge_type=EdgeType.REFERENCES, source_id="v3", target_id="ref")
        )
        assert supersede_chain(g, "v1") == ["v3", "v2", "v1"]

    def test_cycle_terminates(self):
        g = WorkstreamGraph()
        for vid in ("a", "b"):
            g.add_node(Node(node_id=vid, node_type=NodeType.DECISION, label=vid))
        g.add_edge(Edge(edge_id="x", edge_type=EdgeType.SUPERSEDES, source_id="a", target_id="b"))
        g.add_edge(Edge(edge_id="y", edge_type=EdgeType.SUPERSEDES, source_id="b", target_id="a"))
        chain = supersede_chain(g, "a")
        assert len(chain) == 2
        assert set(chain) == {"a", "b"}

    def test_deactivated_edge_shortens_chain(self):
        g = version_graph()
        g.deactivate_edge("s2")
        assert supersede_chain(g, "v1") == ["v2", "v1"]


class TestContradictionPairs:
    def test_pairs_sorted_and_deduped(self):
        g = WorkstreamGraph()
        for nid in ("d1", "d2"):
            g.add_node(Node(node_id=nid, node_type=NodeType.DECISION, label=nid))
        g.add_edge(
            Edge(edge_id="c1", edge_type=EdgeType.CONTRADICTS, source_id="d2", target_id="d1")
        )
        g.add_edge(
            Edge(edge_id="c2", edge_type=EdgeType.CONTRADICTS, source_id="d1", target_id="d2")
        )
        assert contradiction_pairs(g) == [("d1", "d2")]

    def test_no_contradictions(self):
        assert contradiction_pairs(version_graph()) == []

    def test_deactivated_contradiction_excluded(self):
        g = WorkstreamGraph()
        for nid in ("d1", "d2"):
            g.add_node(Node(node_id=nid, node_type=NodeType.DECISION, label=nid))
        g.add_edge(
            Edge(edge_id="c1", edge_type=EdgeType.CONTRADICTS, source_id="d1", target_id="d2")
        )
        g.deactivate_edge("c1")
        assert contradiction_pairs(g) == []
