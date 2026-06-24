"""Graph census reporting across types and activity states."""

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    graph_stats,
)


def make_graph() -> WorkstreamGraph:
    g = WorkstreamGraph()
    g.add_node(Node(node_id="p1", node_type=NodeType.PERSON, label="Ana"))
    g.add_node(Node(node_id="p2", node_type=NodeType.PERSON, label="Bo"))
    g.add_node(Node(node_id="pr1", node_type=NodeType.PROJECT, label="Atlas"))
    g.add_node(Node(node_id="d1", node_type=NodeType.DECISION, label="pick stack"))
    g.add_edge(Edge(edge_id="e1", edge_type=EdgeType.PARTICIPATES, source_id="p1", target_id="pr1"))
    g.add_edge(Edge(edge_id="e2", edge_type=EdgeType.OWNS, source_id="p2", target_id="pr1"))
    g.add_edge(Edge(edge_id="e3", edge_type=EdgeType.REFERENCES, source_id="d1", target_id="pr1"))
    return g


class TestGraphStats:
    def test_empty_graph(self):
        stats = graph_stats(WorkstreamGraph())
        assert stats == {
            "nodes": 0,
            "edges": 0,
            "active_nodes": 0,
            "active_edges": 0,
            "nodes_by_type": {},
            "edges_by_type": {},
        }

    def test_counts_by_type(self):
        stats = graph_stats(make_graph())
        assert stats["nodes"] == 4
        assert stats["edges"] == 3
        assert stats["nodes_by_type"] == {"decision": 1, "person": 2, "project": 1}
        assert stats["edges_by_type"] == {"owns": 1, "participates": 1, "references": 1}

    def test_deactivation_moves_counts(self):
        g = make_graph()
        g.deactivate_node("p1")
        stats = graph_stats(g)
        assert stats["nodes"] == 4  # still present...
        assert stats["active_nodes"] == 3  # ...but inactive
        assert stats["active_edges"] == 2  # e1 deactivated with its endpoint

    def test_type_keys_sorted(self):
        stats = graph_stats(make_graph())
        assert list(stats["nodes_by_type"]) == sorted(stats["nodes_by_type"])
        assert list(stats["edges_by_type"]) == sorted(stats["edges_by_type"])

    def test_deterministic(self):
        assert graph_stats(make_graph()) == graph_stats(make_graph())
