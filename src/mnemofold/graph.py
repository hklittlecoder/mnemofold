"""Workstream graph: nodes and typed edges.

The workstream graph models entities and relationships extracted from
work events. Nodes represent things like people, projects, commitments,
decisions; edges represent relationships like participates, owns,
references, supersedes, contradicts.
"""

from __future__ import annotations

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

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by id."""
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Edge | None:
        """Get an edge by id."""
        return self.edges.get(edge_id)

    def outgoing_edges(self, node_id: str) -> list[Edge]:
        """Get all edges starting from node_id."""
        return [self.edges[eid] for eid in self._outgoing.get(node_id, [])]

    def incoming_edges(self, node_id: str) -> list[Edge]:
        """Get all edges ending at node_id."""
        return [self.edges[eid] for eid in self._incoming.get(node_id, [])]

    def neighbors(self, node_id: str) -> list[Node]:
        """Get all nodes connected to node_id (any direction)."""
        result: set[str] = set()
        for e in self.outgoing_edges(node_id):
            result.add(e.target_id)
        for e in self.incoming_edges(node_id):
            result.add(e.source_id)
        return [self.nodes[nid] for nid in result if nid in self.nodes]

    def nodes_by_type(self, node_type: NodeType) -> list[Node]:
        """Get all nodes of a given type."""
        if isinstance(node_type, str):
            node_type = NodeType(node_type)
        return [n for n in self.nodes.values() if n.node_type == node_type and n.active]

    def edge_count(self) -> int:
        """Return the number of active edges."""
        return sum(1 for e in self.edges.values() if e.active)

    def node_count(self) -> int:
        """Return the number of active nodes."""
        return sum(1 for n in self.nodes.values() if n.active)
