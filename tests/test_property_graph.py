"""Randomized checks that the graph audit never misses a planted defect.

Graphs are generated with seeded RNGs only; every assertion holds for
the whole seed sweep, not for a hand-picked case.
"""

import random

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    audit_graph,
)

NON_PROVENANCE = [EdgeType.PARTICIPATES, EdgeType.REFERENCES, EdgeType.MENTIONS]


def build_random_graph(seed: int) -> WorkstreamGraph:
    rng = random.Random(seed)
    g = WorkstreamGraph()
    n = rng.randint(3, 12)
    for i in range(n):
        g.add_node(Node(node_id=f"n{i}", node_type=NodeType.PERSON, label=f"person {i}"))
    ids = [f"n{i}" for i in range(n)]
    for k in range(rng.randint(2, 20)):
        a, b = rng.choice(ids), rng.choice(ids)
        if a == b:
            continue
        g.add_edge(
            Edge(edge_id=f"e{k}", edge_type=rng.choice(NON_PROVENANCE), source_id=a, target_id=b)
        )
    return g


class TestAuditProperties:
    def test_clean_random_graphs_always_pass(self):
        for seed in range(30):
            assert audit_graph(build_random_graph(seed)).ok, seed

    def test_planted_provenance_cycle_always_found(self):
        for seed in range(15):
            g = build_random_graph(seed)
            g.add_node(Node(node_id="c1", node_type=NodeType.DOCUMENT, label="c1"))
            g.add_node(Node(node_id="c2", node_type=NodeType.DOCUMENT, label="c2"))
            g.add_edge(
                Edge(edge_id="cx1", edge_type=EdgeType.DERIVED_FROM, source_id="c1", target_id="c2")
            )
            g.add_edge(
                Edge(edge_id="cx2", edge_type=EdgeType.SUPERSEDES, source_id="c2", target_id="c1")
            )
            audit = audit_graph(g)
            assert not audit.provenance_acyclic, seed
            assert not audit.ok, seed

    def test_planted_dangling_edge_always_listed(self):
        for seed in range(15):
            g = build_random_graph(seed)
            g.add_node(Node(node_id="dx", node_type=NodeType.PROJECT, label="dx"))
            g.add_node(Node(node_id="dy", node_type=NodeType.PROJECT, label="dy"))
            g.add_edge(
                Edge(edge_id="dxy", edge_type=EdgeType.PART_OF, source_id="dx", target_id="dy")
            )
            del g.nodes["dy"]
            audit = audit_graph(g)
            assert "dxy" in audit.dangling_edges, seed
            assert not audit.ok, seed

    def test_audit_is_deterministic_for_identical_graphs(self):
        for seed in range(10):
            a = audit_graph(build_random_graph(seed)).to_dict()
            b = audit_graph(build_random_graph(seed)).to_dict()
            assert a == b, seed

    def test_counts_always_match_the_graph(self):
        for seed in range(10):
            g = build_random_graph(seed)
            audit = audit_graph(g)
            assert audit.node_count == len(g.nodes)
            assert audit.edge_count == len(g.edges)
