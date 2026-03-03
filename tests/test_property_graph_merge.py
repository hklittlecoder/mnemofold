"""Randomized merge invariants: no dangling edges, stable digests.

Every merged graph must pass the structural audit regardless of how the
inputs were built, merging must be input-order stable for disjoint
graphs, and repeated merges must converge (idempotence).
"""

import random

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    audit_graph,
    merge_graphs,
)

EDGE_TYPES = [EdgeType.PARTICIPATES, EdgeType.REFERENCES, EdgeType.MENTIONS]


def random_graph(seed: int, prefix: str) -> WorkstreamGraph:
    rng = random.Random(seed)
    g = WorkstreamGraph()
    n = rng.randint(2, 8)
    for i in range(n):
        g.add_node(Node(node_id=f"{prefix}n{i}", node_type=NodeType.PERSON, label=f"{prefix}{i}"))
    ids = [f"{prefix}n{i}" for i in range(n)]
    for k in range(rng.randint(1, 10)):
        a, b = rng.choice(ids), rng.choice(ids)
        if a == b:
            continue
        g.add_edge(
            Edge(
                edge_id=f"{prefix}e{k}",
                edge_type=rng.choice(EDGE_TYPES),
                source_id=a,
                target_id=b,
            )
        )
    return g


class TestMergeProperties:
    def test_merged_graph_always_passes_audit(self):
        for seed in range(20):
            a = random_graph(seed, "a")
            b = random_graph(seed + 1000, "b")
            merged, _ = merge_graphs(a, b)
            assert audit_graph(merged).ok, seed

    def test_disjoint_merge_is_commutative_in_content(self):
        for seed in range(10):
            a = random_graph(seed, "a")
            b = random_graph(seed + 1000, "b")
            ab, _ = merge_graphs(a, b)
            ba, _ = merge_graphs(b, a)
            assert ab.to_dict() == ba.to_dict(), seed

    def test_merge_is_idempotent(self):
        for seed in range(10):
            a = random_graph(seed, "a")
            b = random_graph(seed + 1000, "b")
            once, _ = merge_graphs(a, b)
            twice, report = merge_graphs(once, b)
            assert twice.to_dict() == once.to_dict(), seed
            assert report.nodes_added == 0
            assert report.edges_added == 0

    def test_counts_add_up(self):
        for seed in range(10):
            a = random_graph(seed, "a")
            b = random_graph(seed + 1000, "b")
            merged, report = merge_graphs(a, b)
            assert merged.node_count() == a.node_count() + report.nodes_added, seed
            assert merged.edge_count() == a.edge_count() + report.edges_added, seed
