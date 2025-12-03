"""Tests for graph traversal helpers: subgraph, shortest path, components."""

from __future__ import annotations

import random

import pytest

from mnemofold.graph import Edge, EdgeType, Node, NodeType, WorkstreamGraph


def _node(nid: str) -> Node:
    return Node(node_id=nid, node_type=NodeType.PERSON, label=nid)


def _edge(source: str, target: str, edge_type: EdgeType = EdgeType.REFERENCES) -> Edge:
    return Edge(
        edge_id=f"{source}->{target}",
        edge_type=edge_type,
        source_id=source,
        target_id=target,
    )


def _chain_graph() -> WorkstreamGraph:
    """a -> b -> c, plus an isolated node and a deactivated branch."""
    graph = WorkstreamGraph()
    for nid in ("a", "b", "c", "lonely", "ghost"):
        graph.add_node(_node(nid))
    graph.add_edge(_edge("a", "b"))
    graph.add_edge(_edge("b", "c"))
    graph.add_edge(_edge("a", "ghost"))
    graph.deactivate_node("ghost")
    return graph


class TestShortestPath:
    def test_chain_path_follows_edges(self):
        assert _chain_graph().shortest_path("a", "c") == ["a", "b", "c"]

    def test_edges_are_traversable_in_both_directions(self):
        assert _chain_graph().shortest_path("c", "a") == ["c", "b", "a"]

    def test_same_node_path_is_singleton(self):
        assert _chain_graph().shortest_path("b", "b") == ["b"]

    def test_disconnected_nodes_have_no_path(self):
        assert _chain_graph().shortest_path("a", "lonely") is None

    def test_unknown_or_inactive_endpoints_have_no_path(self):
        graph = _chain_graph()
        assert graph.shortest_path("a", "ghost") is None
        assert graph.shortest_path("missing", "a") is None

    def test_deactivated_edge_breaks_the_path(self):
        graph = _chain_graph()
        graph.deactivate_edge("b->c")
        assert graph.shortest_path("a", "c") is None


class TestConnectedComponents:
    def test_components_group_reachable_nodes(self):
        assert _chain_graph().connected_components() == [["a", "b", "c"], ["lonely"]]

    def test_inactive_nodes_are_excluded(self):
        components = _chain_graph().connected_components()
        assert "ghost" not in {nid for component in components for nid in component}

    def test_empty_graph_has_no_components(self):
        assert WorkstreamGraph().connected_components() == []


class TestReachableNodes:
    def test_reachable_from_start_includes_component(self):
        graph = _chain_graph()
        reachable = graph.reachable_nodes("a")
        assert reachable == {"a", "b", "c"}

    def test_reachable_from_lonely_is_just_self(self):
        graph = _chain_graph()
        reachable = graph.reachable_nodes("lonely")
        assert reachable == {"lonely"}

    def test_reachable_unknown_node_returns_empty(self):
        graph = _chain_graph()
        assert graph.reachable_nodes("nope") == set()

    def test_reachable_filters_by_edge_type(self):
        graph = WorkstreamGraph()
        for nid in ("a", "b", "c"):
            graph.add_node(_node(nid))
        graph.add_edge(_edge("a", "b", EdgeType.PARTICIPATES))
        graph.add_edge(_edge("b", "c", EdgeType.REFERENCES))
        # Following only PARTICIPATES edges: a reaches b, but not c
        reachable = graph.reachable_nodes("a", edge_types={EdgeType.PARTICIPATES})
        assert reachable == {"a", "b"}

    def test_degree_counts_incident_edges(self):
        graph = _chain_graph()
        assert graph.degree("a") == 1
        assert graph.degree("b") == 2
        assert graph.degree("c") == 1
        assert graph.degree("lonely") == 0

    def test_degree_missing_node_is_zero(self):
        graph = _chain_graph()
        assert graph.degree("nope") == 0


class TestSubgraph:
    def test_induced_subgraph_keeps_internal_edges_only(self):
        sub = _chain_graph().subgraph(["a", "b"])
        assert sorted(sub.nodes) == ["a", "b"]
        assert sorted(sub.edges) == ["a->b"]
        assert sub.check_no_dangling_edges() == []

    def test_unknown_and_inactive_ids_are_ignored(self):
        sub = _chain_graph().subgraph(["a", "missing", "ghost"])
        assert sorted(sub.nodes) == ["a"]
        assert sub.edges == {}

    def test_subgraph_survives_serialization_roundtrip(self):
        sub = _chain_graph().subgraph(["a", "b", "c"])
        restored = WorkstreamGraph.from_dict(sub.to_dict())
        assert restored.to_dict() == sub.to_dict()
        assert restored.shortest_path("a", "c") == ["a", "b", "c"]

    def test_deactivated_edge_is_not_copied(self):
        graph = _chain_graph()
        graph.deactivate_edge("a->b")
        assert graph.subgraph(["a", "b"]).edges == {}


def _random_graph(rng: random.Random, n: int) -> WorkstreamGraph:
    graph = WorkstreamGraph()
    for i in range(n):
        graph.add_node(_node(f"n{i:02d}"))
    for i in range(1, n):
        if rng.random() < 0.75:
            graph.add_edge(_edge(f"n{rng.randrange(i):02d}", f"n{i:02d}"))
    return graph


class TestRandomGraphProperties:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_components_partition_every_node_exactly_once(self, seed):
        graph = _random_graph(random.Random(seed), 14)
        flat = [nid for component in graph.connected_components() for nid in component]
        assert sorted(flat) == sorted(graph.nodes)
        assert len(flat) == len(set(flat))

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_paths_only_use_edges_that_exist(self, seed):
        graph = _random_graph(random.Random(seed + 30), 14)
        active_pairs = {
            frozenset((edge.source_id, edge.target_id))
            for edge in graph.edges.values()
            if edge.active
        }
        ids = sorted(graph.nodes)
        for source, target in zip(ids, reversed(ids), strict=False):
            path = graph.shortest_path(source, target)
            if path is None:
                continue
            assert path[0] == source
            assert path[-1] == target
            for first, second in zip(path, path[1:], strict=False):
                assert frozenset((first, second)) in active_pairs

    @pytest.mark.parametrize("seed", [1, 2])
    def test_nodes_in_one_component_reach_each_other(self, seed):
        graph = _random_graph(random.Random(seed + 60), 12)
        for component in graph.connected_components():
            for target in component[1:]:
                assert graph.shortest_path(component[0], target) is not None

    @pytest.mark.parametrize("seed", [1, 2])
    def test_random_subgraphs_never_dangle(self, seed):
        rng = random.Random(seed + 90)
        graph = _random_graph(rng, 12)
        ids = sorted(graph.nodes)
        subset = rng.sample(ids, rng.randint(1, len(ids)))
        sub = graph.subgraph(subset)
        assert sub.check_no_dangling_edges() == []
        assert set(sub.nodes) <= set(subset)
