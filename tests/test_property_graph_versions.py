"""Random linear and branching version histories: chains stay consistent.

For seeded random chains, every entry point must yield the same full
chain, chains must contain no duplicates, and contradiction pairs must
be orientation-insensitive.
"""

import random

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    contradiction_pairs,
    supersede_chain,
)


def linear_history(seed: int, length: int) -> tuple[WorkstreamGraph, list[str]]:
    rng = random.Random(seed)
    g = WorkstreamGraph()
    versions = [f"v{i}" for i in range(length)]
    order = versions[:]
    rng.shuffle(order)  # insert order differs from version order
    for vid in order:
        g.add_node(Node(node_id=vid, node_type=NodeType.DECISION, label=vid))
    for newer, older in zip(versions[1:], versions, strict=False):
        g.add_edge(
            Edge(
                edge_id=f"s-{newer}-{older}",
                edge_type=EdgeType.SUPERSEDES,
                source_id=newer,
                target_id=older,
            )
        )
    return g, versions


class TestChainProperties:
    def test_every_entry_point_yields_full_chain(self):
        for seed in range(12):
            g, versions = linear_history(seed, 6)
            expected = list(reversed(versions))
            for start in versions:
                assert supersede_chain(g, start) == expected, (seed, start)

    def test_chains_have_no_duplicates(self):
        for seed in range(12):
            g, versions = linear_history(seed, 8)
            chain = supersede_chain(g, versions[seed % len(versions)])
            assert len(chain) == len(set(chain)), seed

    def test_contradiction_pairs_orientation_insensitive(self):
        for seed in range(12):
            rng = random.Random(seed)
            g = WorkstreamGraph()
            g.add_node(Node(node_id="a", node_type=NodeType.DECISION, label="a"))
            g.add_node(Node(node_id="b", node_type=NodeType.DECISION, label="b"))
            first, second = ("a", "b") if rng.random() < 0.5 else ("b", "a")
            g.add_edge(
                Edge(
                    edge_id="c",
                    edge_type=EdgeType.CONTRADICTS,
                    source_id=first,
                    target_id=second,
                )
            )
            assert contradiction_pairs(g) == [("a", "b")], seed

    def test_chain_length_matches_history(self):
        for seed in range(8):
            g, versions = linear_history(seed, 5)
            assert len(supersede_chain(g, "v0")) == len(versions), seed
