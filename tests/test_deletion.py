from datetime import UTC, datetime

from mnemofold.deletion import (
    DeletionEngine,
    DeletionReason,
    GraphDeletionTarget,
    Tombstone,
    TombstoneIndex,
)

NOW = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)


def _make_fixture():
    """Build a small graph: a -> b -> c, a -> d."""
    targets = {
        "a": GraphDeletionTarget("a", "node", outgoing_relations=["b", "d"]),
        "b": GraphDeletionTarget("b", "node", outgoing_relations=["c"]),
        "c": GraphDeletionTarget("c", "node"),
        "d": GraphDeletionTarget("d", "node"),
        "e": GraphDeletionTarget("e", "node", outgoing_relations=["a"]),  # incoming-style
    }
    deleted: set[str] = set()

    def get_target(k):
        return targets.get(k)

    def delete_item(k, kind, reason, now):
        deleted.add(k)
        return True

    engine = DeletionEngine(get_target=get_target, delete_item=delete_item)
    return engine, targets, deleted


def test_tombstone_index_basic():
    idx = TombstoneIndex()
    ts = Tombstone(key="k1", kind="node", reason=DeletionReason.FORGET, deleted_at=NOW)
    idx.add(ts)
    assert idx.has("k1")
    assert not idx.has("k2")
    assert idx.get("k1") is ts
    assert idx.count() == 1


def test_tombstone_index_all():
    idx = TombstoneIndex()
    idx.add(Tombstone("a", "n", DeletionReason.FORGET, NOW))
    idx.add(Tombstone("b", "n", DeletionReason.USER_REQUEST, NOW))
    assert idx.count() == 2
    assert len(idx.all()) == 2


def test_deletion_basic_cascade():
    engine, targets, deleted = _make_fixture()
    report = engine.delete("a", DeletionReason.FORGET, NOW, requested_by="user1")
    assert report.requested_key == "a"
    assert report.total_deleted == 4
    assert "a" in deleted
    assert "b" in deleted
    assert "c" in deleted
    assert "d" in deleted
    assert "e" not in deleted


def test_deletion_leaf_node():
    engine, targets, deleted = _make_fixture()
    report = engine.delete("c", DeletionReason.DATA_EXPIRY, NOW)
    assert report.total_deleted == 1
    assert "c" in deleted
    assert "a" not in deleted


def test_deletion_blocks_protected():
    engine, targets, deleted = _make_fixture()
    protected = {"b"}

    def is_protected(k):
        return k in protected

    engine2 = DeletionEngine(
        get_target=engine._get_target,
        delete_item=engine._delete_item,
        is_protected=is_protected,
    )
    report = engine2.delete("a", DeletionReason.FORGET, NOW)
    assert "a" in deleted
    assert "d" in deleted
    assert "b" not in deleted
    assert "c" not in deleted
    assert "b" in report.blocked


def test_deletion_idempotent():
    engine, targets, deleted = _make_fixture()
    r1 = engine.delete("a", DeletionReason.FORGET, NOW)
    r2 = engine.delete("a", DeletionReason.FORGET, NOW)
    assert r2.total_deleted == 0
    assert engine.tombstones.count() == r1.total_deleted


def test_deletion_handles_cycles():
    targets = {
        "x": GraphDeletionTarget("x", "node", outgoing_relations=["y"]),
        "y": GraphDeletionTarget("y", "node", outgoing_relations=["x"]),
    }
    deleted: set[str] = set()
    engine = DeletionEngine(
        get_target=lambda k: targets.get(k),
        delete_item=lambda k, kind, reason, now: deleted.add(k) or True,
    )
    report = engine.delete("x", DeletionReason.USER_REQUEST, NOW)
    assert report.total_deleted == 2
    assert "x" in deleted and "y" in deleted
    assert len(report.errors) == 0


def test_deletion_unknown_key():
    engine, targets, deleted = _make_fixture()
    report = engine.delete("z", DeletionReason.FORGET, NOW)
    assert report.total_deleted == 0
    assert any("not found" in e for e in report.errors)


def test_is_deleted_check():
    engine, targets, deleted = _make_fixture()
    engine.delete("a", DeletionReason.FORGET, NOW)
    assert engine.is_deleted("a")
    assert engine.is_deleted("b")
    assert not engine.is_deleted("e")


def test_audit_report_counts():
    engine, targets, deleted = _make_fixture()
    engine.delete("c", DeletionReason.DATA_EXPIRY, NOW)
    engine.delete("d", DeletionReason.USER_REQUEST, NOW)
    counts = engine.audit_report()
    assert counts["data_expiry"] == 1
    assert counts["user_request"] == 1


def test_deletion_report_properties():
    engine, targets, deleted = _make_fixture()
    report = engine.delete("a", DeletionReason.FORGET, NOW)
    assert report.requested_key == "a"
    assert report.reason == DeletionReason.FORGET
    assert report.requested_at == NOW
    assert report.total_deleted == len(report.deleted)
    # Cascade depth increases with distance
    depths = {entry.key: entry.cascade_depth for entry in report.deleted}
    assert depths["a"] == 0
    assert depths["b"] == 1
    assert depths["c"] == 2
    assert depths["d"] == 1


def test_summary_dict_groups_by_kind():
    engine, targets, deleted = _make_fixture()
    report = engine.delete("a", DeletionReason.FORGET, NOW)
    summary = report.summary_dict()
    assert summary["requested_key"] == "a"
    assert summary["total_deleted"] == report.total_deleted
    assert "deleted_by_kind" in summary
    assert summary["blocked_count"] == len(report.blocked)
    assert summary["error_count"] == len(report.errors)
    assert isinstance(summary["deleted_by_kind"], dict)
    assert summary["deleted_by_kind"] == dict(sorted(summary["deleted_by_kind"].items()))


def test_mixed_kind_cascade_summary():
    targets = {
        "person_alice": GraphDeletionTarget(
            "person_alice", "person", outgoing_relations=["doc_memo", "commit_c1"]
        ),
        "doc_memo": GraphDeletionTarget("doc_memo", "document"),
        "commit_c1": GraphDeletionTarget("commit_c1", "commitment"),
    }
    deleted: set[str] = set()

    def get_target(k):
        return targets.get(k)

    def delete_item(k, kind, reason, now):
        deleted.add(k)
        return True

    engine = DeletionEngine(get_target=get_target, delete_item=delete_item)
    report = engine.delete("person_alice", DeletionReason.FORGET, NOW)
    summary = report.summary_dict()
    assert summary["deleted_by_kind"]["person"] == 1
    assert summary["deleted_by_kind"]["document"] == 1
    assert summary["deleted_by_kind"]["commitment"] == 1
    assert summary["total_deleted"] == 3
