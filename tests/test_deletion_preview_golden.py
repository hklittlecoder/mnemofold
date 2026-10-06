"""Golden bytes for the deletion cascade dry-run plan."""

import json
from datetime import UTC, datetime
from pathlib import Path

from mnemofold.canon import canonical_json
from mnemofold.deletion import (
    DeletionEngine,
    DeletionReason,
    GraphDeletionTarget,
)

FIXTURE = Path(__file__).parent / "fixtures" / "deletion_preview_golden.json"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def make_engine() -> DeletionEngine:
    targets = {
        "root": GraphDeletionTarget(
            key="root", kind="memory", outgoing_relations=["child", "held", "ghost"]
        ),
        "child": GraphDeletionTarget(key="child", kind="edge", outgoing_relations=["leaf"]),
        "leaf": GraphDeletionTarget(key="leaf", kind="memory", outgoing_relations=[]),
        "held": GraphDeletionTarget(key="held", kind="memory", outgoing_relations=[]),
    }
    return DeletionEngine(
        get_target=lambda key: targets.get(key),
        delete_item=lambda key, kind, reason, now: True,
        is_protected=lambda key: key == "held",
    )


class TestPreviewGolden:
    def test_matches_golden_bytes(self):
        preview = make_engine().preview("root")
        assert canonical_json(preview.to_dict()) == FIXTURE.read_text(encoding="utf-8")

    def test_golden_shape(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert payload["total"] == 3
        assert payload["blocked"] == ["held"]
        assert payload["missing"] == ["ghost"]
        assert [e["depth"] for e in payload["would_delete"]] == [0, 1, 2]

    def test_preview_then_delete_agree(self):
        plan = make_engine().preview("root").keys()
        report = make_engine().delete("root", DeletionReason.USER_REQUEST, NOW)
        assert [entry.key for entry in report.deleted] == plan
