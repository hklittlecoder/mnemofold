"""Example: 180-day work history -> workstream graph + commitment ledger.

Runs fully offline on a seeded synthetic history. It ingests events into
episodic memory, builds a workstream graph (people, projects, and the
commitments that link them), constructs a commitment ledger from the
extracted commitments, and measures commitment recall/precision against
the factory's planted ground truth.

Every number printed here is measured from this run on synthetic data —
there is no real corpus, no network access, and no trained model.

Run:
    python examples/history_workstream/run.py
"""

from __future__ import annotations

from mnemofold.evaluation import precision, recall
from mnemofold.factory import FactoryConfig, WorkHistoryFactory
from mnemofold.graph import Edge, EdgeType, Node, NodeType, WorkstreamGraph
from mnemofold.ingest import IngestPipeline
from mnemofold.ledger import Commitment, CommitmentLedger

SEED = 42
DAYS = 180


def build_graph(people: set[str], projects: set[str], links: list[tuple[str, str, str]]):
    """Build a workstream graph: person -> commitment -> project."""
    graph = WorkstreamGraph()
    for person in sorted(people):
        graph.add_node(Node(node_id=f"person:{person}", node_type=NodeType.PERSON, label=person))
    for project in sorted(projects):
        graph.add_node(
            Node(node_id=f"project:{project}", node_type=NodeType.PROJECT, label=project)
        )
    for commitment_id, person, project in links:
        node_id = f"commitment:{commitment_id}"
        graph.add_node(Node(node_id=node_id, node_type=NodeType.COMMITMENT, label=commitment_id))
        if graph.get_node(f"person:{person}") is not None:
            graph.add_edge(
                Edge(
                    edge_id=f"owns:{commitment_id}",
                    edge_type=EdgeType.OWNS,
                    source_id=f"person:{person}",
                    target_id=node_id,
                )
            )
        if graph.get_node(f"project:{project}") is not None:
            graph.add_edge(
                Edge(
                    edge_id=f"partof:{commitment_id}",
                    edge_type=EdgeType.PART_OF,
                    source_id=node_id,
                    target_id=f"project:{project}",
                )
            )
    return graph


def main() -> int:
    factory = WorkHistoryFactory(seed=SEED, days=DAYS, config=FactoryConfig(include_designer=True))
    events, manifest = factory.generate()
    typed = [event.to_event() for event in events]

    result = IngestPipeline().run(typed)

    planted = {p.item_id: p for p in factory.planted_items() if p.kind == "commitment"}
    planted_keys = {(p.data["description"], p.data["due_date"][:10]) for p in planted.values()}

    ledger = CommitmentLedger()
    people: set[str] = set()
    projects: set[str] = set()
    links: list[tuple[str, str, str]] = []
    extracted_keys: set[tuple[str, str]] = set()

    structured = [m for m in result.commitments if m.evidence.field == "commitment_ref"]
    ref_of_key = {
        (p.data["description"], p.data["due_date"][:10]): ref for ref, p in planted.items()
    }
    for mention in structured:
        key = (mention.description, mention.due or "")
        extracted_keys.add(key)
        ref = ref_of_key.get(key)
        if ref is None:
            continue
        project = planted[ref].data["project"]
        ledger.add(
            Commitment(
                commitment_id=ref,
                owed_by=mention.debtor,
                owed_to=mention.creditor,
                description=mention.description,
                due_date=planted[ref].data["due_date"],
            )
        )
        people.add(mention.debtor)
        projects.add(project)
        links.append((ref, mention.debtor, project))

    graph = build_graph(people, projects, links)

    recovered = planted_keys & extracted_keys
    recall_score = recall(planted_keys, recovered)
    precision_score = precision(planted_keys, extracted_keys)

    print("=== history_workstream: 180-day synthetic history ===")
    print(f"seed={SEED} days={DAYS} checksum={manifest.checksum}")
    print(f"events={manifest.event_count}  episodes={len(result.episodes)}")
    print(
        f"graph: nodes={graph.node_count()} edges={graph.edge_count()} "
        f"dangling={len(graph.check_no_dangling_edges())} "
        f"acyclic={graph.check_provenance_acyclic()}"
    )
    print(f"ledger commitments: {ledger.total_count()}")
    print(f"planted commitments: {len(planted_keys)}")
    print(f"commitment recall:    {recall_score:.4f}  (measured on synthetic data)")
    print(f"commitment precision: {precision_score:.4f}  (measured on synthetic data)")

    ok = (
        recall_score == 1.0
        and graph.check_provenance_acyclic()
        and not graph.check_no_dangling_edges()
    )
    print(f"RESULT: {'OK' if ok else 'CHECK FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
