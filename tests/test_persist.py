"""Envelope serialization, validation and rejection boundaries."""

import json

import pytest

from mnemofold.persist import (
    PersistError,
    dump_envelope,
    parse_envelope,
    read_envelope,
    wrap_envelope,
    write_envelope,
)


class TestEnvelope:
    def test_roundtrip(self):
        text = dump_envelope("thing", {"a": 1})
        assert parse_envelope(text, "thing") == {"a": 1}

    def test_envelope_is_self_describing(self):
        env = wrap_envelope("thing", {"a": 1})
        assert env == {"schema": "thing", "schema_version": 1, "payload": {"a": 1}}

    def test_golden_canonical_bytes(self):
        assert (
            dump_envelope("demo", {"x": 1})
            == '{"payload":{"x":1},"schema":"demo","schema_version":1}'
        )

    def test_bytes_are_key_order_independent(self):
        assert dump_envelope("t", {"a": 1, "b": 2}) == dump_envelope("t", {"b": 2, "a": 1})

    def test_schema_mismatch_rejected(self):
        text = dump_envelope("thing", {"a": 1})
        with pytest.raises(PersistError, match="schema mismatch"):
            parse_envelope(text, "other")

    def test_version_mismatch_rejected(self):
        text = dump_envelope("thing", {"a": 1}, version=2)
        with pytest.raises(PersistError, match="schema_version"):
            parse_envelope(text, "thing", version=1)

    def test_explicit_version_roundtrip(self):
        text = dump_envelope("thing", {"a": 1}, version=3)
        assert parse_envelope(text, "thing", version=3) == {"a": 1}

    def test_malformed_json_rejected(self):
        with pytest.raises(PersistError, match="malformed"):
            parse_envelope("{not json", "thing")

    def test_non_object_envelope_rejected(self):
        with pytest.raises(PersistError, match="not a JSON object"):
            parse_envelope("[1, 2, 3]", "thing")

    def test_non_object_payload_rejected(self):
        text = json.dumps({"schema": "thing", "schema_version": 1, "payload": [1, 2]})
        with pytest.raises(PersistError, match="payload"):
            parse_envelope(text, "thing")

    def test_file_roundtrip(self, tmp_path):
        p = tmp_path / "x.json"
        write_envelope(p, "thing", {"a": [1, 2, 3]})
        assert read_envelope(p, "thing") == {"a": [1, 2, 3]}

    def test_file_bytes_match_dump(self, tmp_path):
        p = tmp_path / "x.json"
        write_envelope(p, "thing", {"a": 1})
        assert p.read_text(encoding="utf-8") == dump_envelope("thing", {"a": 1})
