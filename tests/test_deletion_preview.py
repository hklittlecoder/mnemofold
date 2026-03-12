"""Dry-run cascade previews must plan delete() exactly, mutating nothing."""

from datetime import UTC, datetime

from mnemofold.deletion import (
    DeletionEngine,
    DeletionReason,
    GraphDeletionTarget,
)

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def make_targets() -> dict[str, GraphDeletionTarget]:
    # a -> b -> c, a -> prot (protected, guards d), a -> ghost (missing)
    return {
        "a": GraphDeletionTarget(key="a", kind="memory", outgoing_relations=["b", "prot", "ghost"]),
        "b": GraphDeletionTarget(key="b", kind="memory", outgoing_relations=["c"]),
        "c": GraphDeletionTarget(key="c", kind="edge", outgoing_relations=[]),
        "prot": GraphDeletionTarget(key="prot", kind="memory", outgoing_relations=["d"]),
        "d": GraphDeletionTarget(key="d", kind="memory", outgoing_relations=[]),
    }


def make_engine(targets, protected=("prot",)):
    deleted: list[str] = []

    def delete_item(key: str, kind: str, reason, now) -> bool:
        deleted.append(key)
        return True

    engine = DeletionEngine(
        get_target=lambda key: targets.get(key),
        delete_item=delete_item,
        is_protected=lambda key: key in protected,
    )
    return engine, deleted


class TestDeletionPreview:
    def test_plan_keys_depths_and_blocks(self):
        engine, _ = make_engine(make_targets())
        preview = engine.preview("a")
        assert preview.keys() == ["a", "b", "c"]
        assert [e["depth"] for e in preview.would_delete] == [0, 1, 2]
        assert [e["kind"] for e in preview.would_delete] == ["memory", "memory", "edge"]
        assert preview.blocked == ["prot"]
        assert preview.missing == ["ghost"]
        assert preview.total == 3

    def test_preview_mutates_nothing(self):
        engine, deleted = make_engine(make_targets())
        engine.preview("a")
        assert deleted == []
        assert engine.tombstones.count() == 0
        assert not engine.is_deleted("a")

    def test_preview_matches_a_subsequent_delete(self):
        targets = make_targets()
        preview_engine, _ = make_engine(targets)
        delete_engine, _ = make_engine(targets)
        preview = preview_engine.preview("a")
        report = delete_engine.delete("a", DeletionReason.USER_REQUEST, NOW)
        assert [e.key for e in report.deleted] == preview.keys()
        assert report.blocked == preview.blocked
        assert report.errors == [f"target not found: {k}" for k in preview.missing]

    def test_unknown_root_previews_as_missing(self):
        engine, _ = make_engine(make_targets())
        preview = engine.preview("nowhere")
        assert preview.would_delete == []
        assert preview.missing == ["nowhere"]

    def test_tombstoned_key_short_circuits(self):
        targets = make_targets()
        engine, _ = make_engine(targets)
        engine.delete("a", DeletionReason.USER_REQUEST, NOW)
        preview = engine.preview("a")
        assert preview.would_delete == []
        assert preview.total == 0

    def test_cycles_terminate(self):
        targets = {
            "x": GraphDeletionTarget(key="x", kind="memory", outgoing_relations=["y"]),
            "y": GraphDeletionTarget(key="y", kind="memory", outgoing_relations=["x"]),
        }
        engine, _ = make_engine(targets, protected=())
        preview = engine.preview("x")
        assert preview.keys() == ["x", "y"]

    def test_to_dict_shape_and_determinism(self):
        engine, _ = make_engine(make_targets())
        d1 = engine.preview("a").to_dict()
        d2 = engine.preview("a").to_dict()
        assert d1 == d2
        assert set(d1) == {"would_delete", "blocked", "missing", "total"}
