"""Workstream graph: nodes and typed edges.

The workstream graph models entities and relationships extracted from
work events. Nodes represent things like people, projects, commitments,
decisions; edges represent relationships like participates, owns,
references, supersedes, contradicts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mnemofold.canon import canonical_json


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
    return canonical_json(obj, ensure_ascii=False)


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

    def subgraph(self, node_ids: Iterable[str]) -> WorkstreamGraph:
        """Induced subgraph over the requested ids (unknown ids ignored).

        Copies the selected nodes and every active edge whose endpoints
        are both selected, so the result never has dangling edges.
        Deactivated nodes are excluded even when explicitly requested.
        """
        selected = {
            nid for nid in node_ids if (node := self.nodes.get(nid)) is not None and node.active
        }
        result = WorkstreamGraph()
        for nid in sorted(selected):
            node = self.nodes[nid]
            result.add_node(Node.from_dict(node.to_dict()))
        for edge in sorted(self.edges.values(), key=lambda e: e.edge_id):
            if not edge.active:
                continue
            if edge.source_id in selected and edge.target_id in selected:
                result.add_edge(Edge.from_dict(edge.to_dict()))
        return result

    def shortest_path(self, source_id: str, target_id: str) -> list[str] | None:
        """Fewest-active-edge chain between two nodes, endpoints included.

        Edges are treated as undirected: workstream relationships carry
        meaning in both directions when answering "how are these two
        related". Returns None when either endpoint is missing or
        inactive, or when no chain of active edges connects them. BFS
        expands neighbors in sorted order, so the same graph always
        yields the same path.
        """
        source = self.nodes.get(source_id)
        target = self.nodes.get(target_id)
        if source is None or target is None or not source.active or not target.active:
            return None
        if source_id == target_id:
            return [source_id]
        adjacency: dict[str, set[str]] = {
            nid: set() for nid, node in self.nodes.items() if node.active
        }
        for edge in self.edges.values():
            if not edge.active:
                continue
            if edge.source_id in adjacency and edge.target_id in adjacency:
                adjacency[edge.source_id].add(edge.target_id)
                adjacency[edge.target_id].add(edge.source_id)
        previous: dict[str, str] = {source_id: ""}
        queue = [source_id]
        while queue:
            current = queue.pop(0)
            for nxt in sorted(adjacency[current]):
                if nxt in previous:
                    continue
                previous[nxt] = current
                if nxt == target_id:
                    path = [target_id]
                    while path[-1] != source_id:
                        path.append(previous[path[-1]])
                    path.reverse()
                    return path
                queue.append(nxt)
        return None

    def reachable_nodes(self, start_id: str, edge_types: set[EdgeType] | None = None) -> set[str]:
        """All active nodes reachable from ``start_id`` via active edges.

        When ``edge_types`` is provided, only edges of those types are
        traversed (useful for walking provenance edges without following
        every relationship). The starting node is always included when
        it exists and is active. Uses BFS with sorted neighbor order so
        results are deterministic; returns an empty set for a missing or
        inactive start node.
        """
        start = self.nodes.get(start_id)
        if start is None or not start.active:
            return set()
        adjacency: dict[str, set[str]] = {
            nid: set() for nid, node in self.nodes.items() if node.active
        }
        for edge in self.edges.values():
            if not edge.active:
                continue
            if edge_types is not None and edge.edge_type not in edge_types:
                continue
            if edge.source_id in adjacency and edge.target_id in adjacency:
                adjacency[edge.source_id].add(edge.target_id)
                adjacency[edge.target_id].add(edge.source_id)
        visited: set[str] = {start_id}
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for nxt in sorted(adjacency.get(current, set())):
                if nxt in visited:
                    continue
                visited.add(nxt)
                queue.append(nxt)
        return visited

    def degree(self, node_id: str) -> int:
        """Count of active edges incident to the given node."""
        node = self.nodes.get(node_id)
        if node is None or not node.active:
            return 0
        count = 0
        for edge in self.edges.values():
            if not edge.active:
                continue
            if edge.source_id == node_id or edge.target_id == node_id:
                count += 1
        return count

    def connected_components(self) -> list[list[str]]:
        """Active nodes grouped by undirected active-edge reachability.

        Deterministic: nodes are sorted inside each component and the
        components are sorted by their first node. The result partitions
        the active node set — every active node appears exactly once.
        """
        adjacency: dict[str, set[str]] = {
            nid: set() for nid, node in self.nodes.items() if node.active
        }
        for edge in self.edges.values():
            if not edge.active:
                continue
            if edge.source_id in adjacency and edge.target_id in adjacency:
                adjacency[edge.source_id].add(edge.target_id)
                adjacency[edge.target_id].add(edge.source_id)
        seen: set[str] = set()
        components: list[list[str]] = []
        for start in sorted(adjacency):
            if start in seen:
                continue
            component: list[str] = []
            stack = [start]
            seen.add(start)
            while stack:
                current = stack.pop()
                component.append(current)
                for nxt in sorted(adjacency[current]):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            components.append(sorted(component))
        return sorted(components)

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


@dataclass(slots=True)
class GraphAudit:
    """Structured verdict of every structural invariant check.

    ``ok`` is the single answer callers need: no dangling edges and an
    acyclic provenance layer. The counts let reports show how much of
    the graph is inactive without a second traversal.
    """

    dangling_edges: list[str] = field(default_factory=list)
    provenance_acyclic: bool = True
    node_count: int = 0
    edge_count: int = 0
    inactive_nodes: int = 0
    inactive_edges: int = 0

    @property
    def ok(self) -> bool:
        return not self.dangling_edges and self.provenance_acyclic

    def to_dict(self) -> dict[str, Any]:
        return {
            "dangling_edges": list(self.dangling_edges),
            "provenance_acyclic": self.provenance_acyclic,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "inactive_nodes": self.inactive_nodes,
            "inactive_edges": self.inactive_edges,
            "ok": self.ok,
        }


def audit_graph(graph: WorkstreamGraph) -> GraphAudit:
    """Run every structural invariant check and return one report.

    Combines dangling-edge detection, provenance acyclicity and
    activity counts so callers (CLI checks, fold reports, CI gates)
    get a single structured verdict instead of running each check by
    hand and re-deriving the counts.
    """
    return GraphAudit(
        dangling_edges=sorted(graph.check_no_dangling_edges()),
        provenance_acyclic=graph.check_provenance_acyclic(),
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        inactive_nodes=sum(1 for n in graph.nodes.values() if not n.active),
        inactive_edges=sum(1 for e in graph.edges.values() if not e.active),
    )


@dataclass(slots=True)
class GraphMergeReport:
    """What one :func:`merge_graphs` call did, deterministically."""

    nodes_added: int = 0
    edges_added: int = 0
    node_conflicts: list[str] = field(default_factory=list)
    edge_conflicts: list[str] = field(default_factory=list)
    dropped_edges: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.node_conflicts or self.edge_conflicts or self.dropped_edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_added": self.nodes_added,
            "edges_added": self.edges_added,
            "node_conflicts": list(self.node_conflicts),
            "edge_conflicts": list(self.edge_conflicts),
            "dropped_edges": list(self.dropped_edges),
            "clean": self.clean,
        }


def merge_graphs(
    base: WorkstreamGraph, other: WorkstreamGraph
) -> tuple[WorkstreamGraph, GraphMergeReport]:
    """Deterministic union of two graphs; inputs are never mutated.

    Nodes and edges present only in ``other`` are added to a fresh copy
    of ``base``. Same-id nodes (or edges) whose checksums differ are
    reported as conflicts and the ``base`` version wins — divergent
    facts are surfaced, never silently blended. Edges whose endpoints
    are missing from the union are dropped and listed, so the merged
    graph always satisfies the no-dangling-edges invariant.
    """
    merged = WorkstreamGraph.from_dict(base.to_dict())
    report = GraphMergeReport()
    for node_id in sorted(other.nodes):
        node = other.nodes[node_id]
        existing = merged.nodes.get(node_id)
        if existing is None:
            merged.add_node(Node.from_dict(node.to_dict()))
            report.nodes_added += 1
        elif node_checksum(existing) != node_checksum(node):
            report.node_conflicts.append(node_id)
    for edge_id in sorted(other.edges):
        edge = other.edges[edge_id]
        if edge_id in merged.edges:
            if edge_checksum(merged.edges[edge_id]) != edge_checksum(edge):
                report.edge_conflicts.append(edge_id)
            continue
        if edge.source_id not in merged.nodes or edge.target_id not in merged.nodes:
            report.dropped_edges.append(edge_id)
            continue
        merged.add_edge(Edge.from_dict(edge.to_dict()))
        report.edges_added += 1
    return merged, report


def supersede_chain(graph: WorkstreamGraph, node_id: str) -> list[str]:
    """Version history of a fact node, newest first.

    A SUPERSEDES edge points from the newer version to the one it
    replaces. Starting from ANY version, the walk climbs to the newest
    version (following incoming edges) and then descends to the
    original, so callers always get the full chain regardless of which
    version they hold. Ties among multiple newer/older versions are
    broken by node id, and cycles terminate via the visited set. An
    unknown node yields an empty chain.
    """
    if node_id not in graph.nodes:
        return []

    def newer(nid: str) -> list[str]:
        return [
            e.source_id
            for e in graph.incoming_edges(nid)
            if e.edge_type == EdgeType.SUPERSEDES and e.source_id in graph.nodes
        ]

    def older(nid: str) -> list[str]:
        return [
            e.target_id
            for e in graph.outgoing_edges(nid)
            if e.edge_type == EdgeType.SUPERSEDES and e.target_id in graph.nodes
        ]

    seen = {node_id}
    top = node_id
    while True:
        candidates = sorted(p for p in newer(top) if p not in seen)
        if not candidates:
            break
        top = candidates[0]
        seen.add(top)
    chain = [top]
    current = top
    while True:
        candidates = sorted(s for s in older(current) if s not in set(chain))
        if not candidates:
            break
        current = candidates[0]
        chain.append(current)
    return chain


def contradiction_pairs(graph: WorkstreamGraph) -> list[tuple[str, str]]:
    """Active CONTRADICTS edges as sorted, deduplicated (a, b) id pairs.

    Direction carries no meaning for a contradiction, so both
    orientations collapse into one canonical pair and the result is
    sorted for deterministic audit reports.
    """
    pairs: set[tuple[str, str]] = set()
    for edge in graph.edges_by_type(EdgeType.CONTRADICTS):
        pair = tuple(sorted((edge.source_id, edge.target_id)))
        pairs.add((pair[0], pair[1]))
    return sorted(pairs)
