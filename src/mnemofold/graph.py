"""Workstream graph: nodes and typed edges.

The workstream graph models entities and relationships extracted from
work events. Nodes represent things like people, projects, commitments,
decisions; edges represent relationships like participates, owns,
references, supersedes, contradicts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeType(StrEnum):
    """Types of nodes in the workstream graph."""

    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    MEETING = "meeting"
    DOCUMENT = "document"
    COMMITMENT = "commitment"
    DECISION = "decision"
    NOTE = "note"
    TASK = "task"


class EdgeType(StrEnum):
    """Types of edges in the workstream graph."""

    PARTICIPATES = "participates"
    OWNS = "owns"
    REFERENCES = "references"
    MENTIONS = "mentions"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    BLOCKS = "blocks"
    PART_OF = "part_of"
    ASSIGNED_TO = "assigned_to"
    ATTENDS = "attends"
    CREATED = "created"


# Edge type categories for invariant checks
PROVENANCE_EDGES = {EdgeType.DERIVED_FROM, EdgeType.SUPERSEDES, EdgeType.PART_OF}


@dataclass(slots=True)
class Node:
    """A node in the workstream graph."""

    node_id: str
    node_type: NodeType
    label: str
    properties: dict[str, Any] = field(default_factory=dict)
    active: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.node_type, str):
            self.node_type = NodeType(self.node_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": str(self.node_type),
            "label": self.label,
            "properties": dict(self.properties),
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Node:
        return cls(
            node_id=d["node_id"],
            node_type=NodeType(d["node_type"]),
            label=d["label"],
            properties=dict(d.get("properties", {})),
            active=d.get("active", True),
        )


@dataclass(slots=True)
class Edge:
    """A directed edge between two nodes in the workstream graph."""

    edge_id: str
    edge_type: EdgeType
    source_id: str
    target_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    active: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.edge_type, str):
            self.edge_type = EdgeType(self.edge_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "edge_type": str(self.edge_type),
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": dict(self.properties),
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Edge:
        return cls(
            edge_id=d["edge_id"],
            edge_type=EdgeType(d["edge_type"]),
            source_id=d["source_id"],
            target_id=d["target_id"],
            properties=dict(d.get("properties", {})),
            active=d.get("active", True),
        )


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def node_checksum(node: Node) -> str:
    """Compute a deterministic checksum for a node."""
    return hashlib.sha256(_canonical_json(node.to_dict()).encode("utf-8")).hexdigest()


def edge_checksum(edge: Edge) -> str:
    """Compute a deterministic checksum for an edge."""
    return hashlib.sha256(_canonical_json(edge.to_dict()).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class WorkstreamGraph:
    """An in-memory workstream graph with nodes and edges.

    Supports adding, removing, and querying nodes and edges.
    Maintains referential integrity: edges cannot reference
    non-existent nodes.
    """

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    _outgoing: dict[str, list[str]] = field(default_factory=dict)
    _incoming: dict[str, list[str]] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        """Add a node to the graph. Idempotent if same id."""
        if node.node_id in self.nodes:
            return
        self.nodes[node.node_id] = node
        self._outgoing.setdefault(node.node_id, [])
        self._incoming.setdefault(node.node_id, [])

    def add_edge(self, edge: Edge) -> None:
        """Add an edge. Raises ValueError if source or target node missing."""
        if edge.edge_id in self.edges:
            return
        if edge.source_id not in self.nodes:
            raise ValueError(f"source node not found: {edge.source_id}")
        if edge.target_id not in self.nodes:
            raise ValueError(f"target node not found: {edge.target_id}")
        self.edges[edge.edge_id] = edge
        self._outgoing[edge.source_id].append(edge.edge_id)
        self._incoming[edge.target_id].append(edge.edge_id)

    def deactivate_node(self, node_id: str) -> None:
        """Deactivate a node and all edges connected to it."""
        if node_id in self.nodes:
            self.nodes[node_id].active = False
        for eid in list(self._outgoing.get(node_id, [])):
            if eid in self.edges:
                self.edges[eid].active = False
        for eid in list(self._incoming.get(node_id, [])):
            if eid in self.edges:
                self.edges[eid].active = False

    def deactivate_edge(self, edge_id: str) -> None:
        """Deactivate an edge."""
        if edge_id in self.edges:
            self.edges[edge_id].active = False

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by id."""
        node = self.nodes.get(node_id)
        return node if node and node.active else None

    def get_edge(self, edge_id: str) -> Edge | None:
        """Get an edge by id."""
        edge = self.edges.get(edge_id)
        return edge if edge and edge.active else None

    def outgoing_edges(self, node_id: str) -> list[Edge]:
        """Get all active edges starting from node_id."""
        return [
            self.edges[eid]
            for eid in self._outgoing.get(node_id, [])
            if eid in self.edges and self.edges[eid].active
        ]

    def incoming_edges(self, node_id: str) -> list[Edge]:
        """Get all active edges ending at node_id."""
        return [
            self.edges[eid]
            for eid in self._incoming.get(node_id, [])
            if eid in self.edges and self.edges[eid].active
        ]

    def neighbors(self, node_id: str) -> list[Node]:
        """Get all active nodes connected to node_id (any direction)."""
        result: set[str] = set()
        for e in self.outgoing_edges(node_id):
            result.add(e.target_id)
        for e in self.incoming_edges(node_id):
            result.add(e.source_id)
        return [self.nodes[nid] for nid in result if nid in self.nodes and self.nodes[nid].active]

    def nodes_by_type(self, node_type: NodeType) -> list[Node]:
        """Get all active nodes of a given type."""
        if isinstance(node_type, str):
            node_type = NodeType(node_type)
        return [n for n in self.nodes.values() if n.node_type == node_type and n.active]

    def edges_by_type(self, edge_type: EdgeType) -> list[Edge]:
        """Get all active edges of a given type."""
        if isinstance(edge_type, str):
            edge_type = EdgeType(edge_type)
        return [e for e in self.edges.values() if e.edge_type == edge_type and e.active]

    def edge_count(self) -> int:
        """Return the number of active edges."""
        return sum(1 for e in self.edges.values() if e.active)

    def node_count(self) -> int:
        """Return the number of active nodes."""
        return sum(1 for n in self.nodes.values() if n.active)

    def check_no_dangling_edges(self) -> list[str]:
        """Return list of edge ids with missing source or target nodes."""
        bad: list[str] = []
        for edge in self.edges.values():
            if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
                bad.append(edge.edge_id)
        return bad

    def check_provenance_acyclic(self) -> bool:
        """Check that provenance edges form a DAG (no cycles)."""
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(nid: str) -> bool:
            visited.add(nid)
            stack.add(nid)
            for edge in self.outgoing_edges(nid):
                if edge.edge_type not in PROVENANCE_EDGES:
                    continue
                if edge.target_id in stack:
                    return False
                if edge.target_id not in visited and not dfs(edge.target_id):
                    return False
            stack.discard(nid)
            return True

        return all(not (nid not in visited and not dfs(nid)) for nid in self.nodes)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a dict."""
        return {
            "nodes": [n.to_dict() for n in sorted(self.nodes.values(), key=lambda n: n.node_id)],
            "edges": [e.to_dict() for e in sorted(self.edges.values(), key=lambda e: e.edge_id)],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkstreamGraph:
        """Deserialize a graph from a dict."""
        g = cls()
        for nd in d.get("nodes", []):
            g.add_node(Node.from_dict(nd))
        for ed in d.get("edges", []):
            g.add_edge(Edge.from_dict(ed))
        return g
