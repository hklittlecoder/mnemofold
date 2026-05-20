"""Golden schemas for the built-in tool registry.

The default registry is the contract planners and policies rely on; its
tool schemas are frozen here so renames, retyping or new defaults fail
deliberately.
"""

import json
from pathlib import Path

from mnemofold.canon import canonical_json
from mnemofold.tools import SideEffectClass, build_default_registry

FIXTURE = Path(__file__).parent / "fixtures" / "tool_registry_schemas_golden.json"


class TestRegistryGolden:
    def test_schemas_match_golden_bytes(self):
        registry = build_default_registry()
        assert canonical_json(registry.schemas()) == FIXTURE.read_text(encoding="utf-8")

    def test_registry_exposes_expected_tools(self):
        registry = build_default_registry()
        names = [spec.name for spec in registry.list_tools()]
        assert names == ["echo", "noop"]
        assert registry.get_spec("echo").required == ["message"]
        assert registry.get_spec("echo").side_effect == SideEffectClass.NONE

    def test_golden_file_is_loadable_json(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert [entry["name"] for entry in payload] == ["echo", "noop"]

    def test_schemas_are_deterministic(self):
        a = build_default_registry().schemas()
        b = build_default_registry().schemas()
        assert canonical_json(a) == canonical_json(b)
