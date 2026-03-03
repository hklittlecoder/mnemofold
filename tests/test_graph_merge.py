"""Deterministic graph union with conflict and dangling-edge handling."""

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    audit_graph,
    merge_graphs,
    node_checksum,
)


def person(pid: str, label: str = "") -> Node:
    return Node(node_id=pid, node_type=NodeType.PERSON, label=label or pid)


def edge(eid: str, src: str, dst: str, etype=EdgeType.REFERENCES) -> Edge:
    return Edge(edge_id=eid, edge_type=etype, source_id=src, target_id=dst)


def graph_a() -> WorkstreamGraph:
    g = WorkstreamGraph()
    g.add_node(person("p1"))
    g.add_node(Node(node_id="pr1", node_type=NodeType.PROJECT, label="Atlas"))
    g.add_edge(edge("e1", "p1", "pr1", EdgeType.PARTICIPATES))
    return g


def graph_b() -> WorkstreamGraph:
    g = WorkstreamGraph()
    g.add_node(person("p1"))  # identical to base
    g.add_node(person("p2"))
    g.add_node(Node(node_id="pr1", node_type=NodeType.PROJECT, label="Atlas RENAMED"))
    g.add_edge(edge("e1", "p1", "pr1", EdgeType.PARTICIPATES))  # identical
    g.add_edge(edge("e2", "p2", "pr1", EdgeType.OWNS))
    return g


class TestMergeGraphs:
    def test_union_adds_new_nodes_and_edges(self):
        merged, report = merge_graphs(graph_a(), graph_b())
        assert report.nodes_added == 1  # p2 only
        assert report.edges_added == 1  # e2 only
        assert merged.node_count() == 3
        assert merged.edge_count() == 2

    def test_identical_duplicates_are_not_conflicts(self):
        _, report = merge_graphs(graph_a(), graph_a())
        assert report.clean
        assert report.nodes_added == 0
        assert report.edges_added == 0

    def test_divergent_node_reported_base_wins(self):
        merged, report = merge_graphs(graph_a(), graph_b())
        assert report.node_conflicts == ["pr1"]
        assert merged.nodes["pr1"].label == "Atlas"

    def test_divergent_edge_reported(self):
        other = WorkstreamGraph()
        other.add_node(person("p1"))
        other.add_node(person("p9"))
        other.add_edge(edge("e1", "p1", "p9", EdgeType.MENTIONS))  # same id, different
        _, report = merge_graphs(graph_a(), other)
        assert report.edge_conflicts == ["e1"]

    def test_dangling_edge_is_dropped(self):
        other = WorkstreamGraph()
        other.add_node(person("p4"))
        # an edge whose target exists nowhere: injecting it directly
        # bypasses add_edge's guard, simulating a corrupt source graph
        other.edges["eBad"] = edge("eBad", "p4", "nowhere")
        merged, report = merge_graphs(graph_a(), other)
        assert report.dropped_edges == ["eBad"]
        assert "eBad" not in merged.edges
        assert merged.nodes["p4"].node_id == "p4"  # the node still merges
        assert audit_graph(merged).ok

    def test_inputs_are_not_mutated(self):
        a, b = graph_a(), graph_b()
        digest_a = node_checksum(a.nodes["pr1"])
        merge_graphs(a, b)
        assert a.node_count() == 2
        assert b.node_count() == 3
        assert node_checksum(a.nodes["pr1"]) == digest_a

    def test_merged_graph_satisfies_invariants(self):
        merged, _ = merge_graphs(graph_a(), graph_b())
        assert audit_graph(merged).ok

    def test_merge_is_deterministic(self):
        m1, r1 = merge_graphs(graph_a(), graph_b())
        m2, r2 = merge_graphs(graph_a(), graph_b())
        assert m1.to_dict() == m2.to_dict()
        assert r1.to_dict() == r2.to_dict()

    def test_empty_other_copies_base(self):
        merged, report = merge_graphs(graph_a(), WorkstreamGraph())
        assert report.clean
        assert merged.to_dict() == graph_a().to_dict()

    def test_report_to_dict_shape(self):
        _, report = merge_graphs(graph_a(), graph_b())
        d = report.to_dict()
        assert set(d) == {
            "nodes_added",
            "edges_added",
            "node_conflicts",
            "edge_conflicts",
            "dropped_edges",
            "clean",
        }
        assert d["clean"] is False
