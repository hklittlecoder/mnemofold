"""Golden and boundary tests for the shared canonical JSON helper."""

import hashlib
import json

from mnemofold.canon import canonical_json, sha256_hex
from mnemofold.graph import Node, NodeType, node_checksum
from mnemofold.plan import Plan
from mnemofold.playbooks import Playbook


class TestCanonicalJson:
    def test_sorts_keys_and_uses_compact_separators(self):
        text = canonical_json({"b": 1, "a": [2, {"d": 4, "c": 3}]})
        assert text == '{"a":[2,{"c":3,"d":4}],"b":1}'

    def test_escapes_non_ascii_by_default(self):
        text = canonical_json({"name": "报告"})
        assert "\\u" in text
        assert json.loads(text)["name"] == "报告"

    def test_keeps_utf8_verbatim_when_requested(self):
        text = canonical_json({"name": "报告"}, ensure_ascii=False)
        assert "报告" in text

    def test_digest_matches_manual_sha256(self):
        payload = {"x": 1, "y": [1, 2, 3]}
        expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        assert sha256_hex(payload) == expected

    def test_digest_ignores_insertion_order(self):
        a = {"x": 1, "y": 2}
        b = {"y": 2, "x": 1}
        assert sha256_hex(a) == sha256_hex(b)

    def test_empty_containers(self):
        assert canonical_json({}) == "{}"
        assert canonical_json([]) == "[]"


class TestDigestParity:
    """Artifact digests must equal sha256 over their own canonical dict form."""

    def test_node_checksum_uses_unescaped_canonical_json(self):
        node = Node(node_id="n1", node_type=NodeType.PERSON, label="Ana 报告")
        manual = hashlib.sha256(
            canonical_json(node.to_dict(), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert node_checksum(node) == manual

    def test_playbook_digest_matches_canonical_form(self):
        pb = Playbook(playbook_id="pb1", name="Release", tags={"b", "a"})
        assert pb.digest() == sha256_hex(pb.to_dict())

    def test_plan_digest_matches_canonical_form(self):
        plan = Plan(plan_id="p1", name="plan")
        assert plan.digest() == sha256_hex(plan.to_dict())
