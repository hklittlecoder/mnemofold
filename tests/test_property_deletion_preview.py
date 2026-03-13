"""Randomized cascades: the dry-run plan is always the executed plan.

Graphs are seeded random relation sets (cycles included) with random
protected keys. For every seed: preview mutates nothing, two previews
agree, and a fresh engine's delete produces exactly the previewed keys,
blocks, and errors.
"""

import random
from datetime import UTC, datetime

from mnemofold.deletion import (
    DeletionEngine,
    DeletionReason,
    GraphDeletionTarget,
)

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def random_targets(seed: int) -> tuple[dict[str, GraphDeletionTarget], list[str]]:
    rng = random.Random(seed)
    keys = [f"k{i}" for i in range(rng.randint(3, 12))]
    targets: dict[str, GraphDeletionTarget] = {}
    for key in keys:
        rels = [rng.choice(keys) for _ in range(rng.randint(0, 3))]
        targets[key] = GraphDeletionTarget(
            key=key,
            kind=rng.choice(["memory", "edge", "node"]),
            outgoing_relations=[r for r in rels if r != key],
        )
    protected = [k for k in keys if rng.random() < 0.2]
    return targets, protected


def make_engine(targets, protected):
    engine = DeletionEngine(
        get_target=lambda key: targets.get(key),
        delete_item=lambda key, kind, reason, now: True,
        is_protected=lambda key: key in protected,
    )
    return engine


class TestPreviewProperties:
    def test_preview_never_mutates(self):
        for seed in range(20):
            targets, protected = random_targets(seed)
            engine = make_engine(targets, protected)
            for key in sorted(targets):
                engine.preview(key)
            assert engine.tombstones.count() == 0, seed

    def test_preview_is_deterministic(self):
        for seed in range(20):
            targets, protected = random_targets(seed)
            engine = make_engine(targets, protected)
            for key in sorted(targets):
                assert engine.preview(key).to_dict() == engine.preview(key).to_dict(), seed

    def test_delete_executes_exactly_the_preview(self):
        for seed in range(20):
            targets, protected = random_targets(seed)
            root = sorted(targets)[0]
            preview = make_engine(targets, protected).preview(root)
            report = make_engine(targets, protected).delete(root, DeletionReason.USER_REQUEST, NOW)
            assert [e.key for e in report.deleted] == preview.keys(), seed
            assert report.blocked == preview.blocked, seed
            assert report.errors == [f"target not found: {k}" for k in preview.missing], seed

    def test_preview_after_delete_is_empty(self):
        for seed in range(10):
            targets, protected = random_targets(seed)
            root = sorted(targets)[0]
            engine = make_engine(targets, protected)
            engine.delete(root, DeletionReason.USER_REQUEST, NOW)
            assert engine.preview(root).total == 0, seed
