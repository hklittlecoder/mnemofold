"""Structural audit reports for the workstream graph."""

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    audit_graph,
)


def make_graph() -> WorkstreamGraph:
    g = WorkstreamGraph()
    g.add_node(Node(node_id="p1", node_type=NodeType.PERSON, label="Ana"))
    g.add_node(Node(node_id="pr1", node_type=NodeType.PROJECT, label="Atlas"))
    g.add_edge(Edge(edge_id="e1", edge_type=EdgeType.PARTICIPATES, source_id="p1", target_id="pr1"))
    return g


class TestGraphAudit:
    def test_clean_graph_passes(self):
        audit = audit_graph(make_graph())
        assert audit.ok
        assert audit.dangling_edges == []
        assert audit.provenance_acyclic
        assert (audit.node_count, audit.edge_count) == (2, 1)
        assert (audit.inactive_nodes, audit.inactive_edges) == (0, 0)

    def test_dangling_edge_is_listed(self):
        g = make_graph()
        del g.nodes["pr1"]
        audit = audit_graph(g)
        assert not audit.ok
        assert audit.dangling_edges == ["e1"]

    def test_provenance_cycle_is_detected(self):
        g = make_graph()
        g.add_node(Node(node_id="d1", node_type=NodeType.DOCUMENT, label="spec v1"))
        g.add_node(Node(node_id="d2", node_type=NodeType.DOCUMENT, label="spec v2"))
        g.add_edge(
            Edge(edge_id="x1", edge_type=EdgeType.DERIVED_FROM, source_id="d2", target_id="d1")
        )
        g.add_edge(
            Edge(edge_id="x2", edge_type=EdgeType.DERIVED_FROM, source_id="d1", target_id="d2")
        )
        audit = audit_graph(g)
        assert not audit.ok
        assert not audit.provenance_acyclic
        assert audit.dangling_edges == []

    def test_non_provenance_cycles_do_not_trip_the_audit(self):
        g = make_graph()
        g.add_node(Node(node_id="m1", node_type=NodeType.MEETING, label="standup"))
        g.add_edge(
            Edge(edge_id="r1", edge_type=EdgeType.REFERENCES, source_id="m1", target_id="p1")
        )
        g.add_edge(Edge(edge_id="r2", edge_type=EdgeType.MENTIONS, source_id="p1", target_id="m1"))
        assert audit_graph(g).provenance_acyclic

    def test_inactive_counts_track_deactivation(self):
        g = make_graph()
        g.deactivate_node("p1")
        audit = audit_graph(g)
        assert audit.ok  # deactivated is not dangling
        assert audit.inactive_nodes == 1
        assert audit.inactive_edges == 1

    def test_to_dict_shape_is_stable(self):
        d = audit_graph(make_graph()).to_dict()
        assert set(d) == {
            "dangling_edges",
            "provenance_acyclic",
            "node_count",
            "edge_count",
            "inactive_nodes",
            "inactive_edges",
            "ok",
        }
        assert d["ok"] is True
