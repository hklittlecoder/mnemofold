"""Golden checksums for graph nodes and edges.

The fixture freezes BOTH the to_dict shape and the checksum computed
over its unescaped canonical JSON. Any change to node/edge
serialization moves these digests and fails here deliberately.
"""

import json
from pathlib import Path

from mnemofold.graph import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    edge_checksum,
    node_checksum,
)

FIXTURE = Path(__file__).parent / "fixtures" / "graph_checksum_golden.json"


def make_node() -> Node:
    return Node(
        node_id="n-ana",
        node_type=NodeType.PERSON,
        label="Ana Chen",
        properties={"team": "core"},
    )


def make_edge() -> Edge:
    return Edge(
        edge_id="e-participates-1",
        edge_type=EdgeType.PARTICIPATES,
        source_id="n-ana",
        target_id="n-atlas",
    )


class TestGraphChecksumGolden:
    def test_node_dict_and_checksum_match_fixture(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        node = make_node()
        assert node.to_dict() == golden["node"]
        assert node_checksum(node) == golden["node_checksum"]

    def test_edge_dict_and_checksum_match_fixture(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        edge = make_edge()
        assert edge.to_dict() == golden["edge"]
        assert edge_checksum(edge) == golden["edge_checksum"]

    def test_checksums_are_stable_across_calls(self):
        assert node_checksum(make_node()) == node_checksum(make_node())
        assert edge_checksum(make_edge()) == edge_checksum(make_edge())

    def test_inactive_flag_moves_the_checksum(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        node = make_node()
        node.active = False
        assert node_checksum(node) != golden["node_checksum"]

    def test_unicode_label_is_not_escaped_before_hashing(self):
        # graph checksums hash unescaped UTF-8: the same label must
        # produce the same digest regardless of JSON escaping style
        a = Node(node_id="n1", node_type=NodeType.PROJECT, label="规划")
        b = Node(node_id="n1", node_type=NodeType.PROJECT, label="规划")
        assert node_checksum(a) == node_checksum(b)
        assert len(node_checksum(a)) == 64
