"""Golden bytes for whole-graph serialization.

Freezes node ordering (sorted by id), edge ordering, and every field of
the node/edge dict forms, so any serialization drift is deliberate.
"""

import json
from pathlib import Path

from mnemofold.canon import canonical_json
from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    WorkstreamGraph,
    audit_graph,
)

FIXTURE = Path(__file__).parent / "fixtures" / "graph_serialization_golden.json"


def make_graph() -> WorkstreamGraph:
    g = WorkstreamGraph()
    g.add_node(Node(node_id="n-atlas", node_type=NodeType.PROJECT, label="Atlas"))
    g.add_node(
        Node(
            node_id="n-ana",
            node_type=NodeType.PERSON,
            label="Ana Chen",
            properties={"team": "core"},
        )
    )
    g.add_edge(
        Edge(
            edge_id="e-participates-1",
            edge_type=EdgeType.PARTICIPATES,
            source_id="n-ana",
            target_id="n-atlas",
            properties={"since": "2026-01-05"},
        )
    )
    return g


class TestGraphSerializationGolden:
    def test_matches_golden_bytes(self):
        assert canonical_json(make_graph().to_dict()) == FIXTURE.read_text(encoding="utf-8")

    def test_nodes_sorted_despite_insertion_order(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert [n["node_id"] for n in payload["nodes"]] == ["n-ana", "n-atlas"]

    def test_roundtrip_from_golden(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        restored = WorkstreamGraph.from_dict(payload)
        assert canonical_json(restored.to_dict()) == FIXTURE.read_text(encoding="utf-8")
        assert audit_graph(restored).ok

    def test_deactivation_reflects_in_serialization(self):
        g = make_graph()
        g.deactivate_node("n-ana")
        payload = json.loads(canonical_json(g.to_dict()))
        ana = next(n for n in payload["nodes"] if n["node_id"] == "n-ana")
        assert ana["active"] is False
