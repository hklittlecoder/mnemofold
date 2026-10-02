"""Golden bytes for the structural graph audit report."""

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

FIXTURE = Path(__file__).parent / "fixtures" / "graph_audit_golden.json"


def broken_graph() -> WorkstreamGraph:
    g = WorkstreamGraph()
    g.add_node(Node(node_id="p1", node_type=NodeType.PERSON, label="Ana"))
    g.add_node(Node(node_id="pr1", node_type=NodeType.PROJECT, label="Atlas"))
    g.add_node(Node(node_id="d1", node_type=NodeType.DOCUMENT, label="spec"))
    g.add_edge(Edge(edge_id="e1", edge_type=EdgeType.PARTICIPATES, source_id="p1", target_id="pr1"))
    g.add_edge(Edge(edge_id="e2", edge_type=EdgeType.REFERENCES, source_id="d1", target_id="pr1"))
    # a dangling edge injected past the add_edge guard, then a deactivation
    g.edges["e_bad"] = Edge(
        edge_id="e_bad", edge_type=EdgeType.MENTIONS, source_id="p1", target_id="ghost"
    )
    g.deactivate_node("d1")
    return g


class TestGraphAuditGolden:
    def test_matches_golden_bytes(self):
        audit = audit_graph(broken_graph())
        assert canonical_json(audit.to_dict()) == FIXTURE.read_text(encoding="utf-8")

    def test_golden_reports_not_ok(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert payload["ok"] is False
        assert payload["dangling_edges"] == ["e_bad"]
        assert payload["inactive_nodes"] == 1
        assert payload["inactive_edges"] == 1

    def test_regeneration_is_stable(self):
        a = audit_graph(broken_graph()).to_dict()
        b = audit_graph(broken_graph()).to_dict()
        assert a == b
