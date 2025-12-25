"""Versioned, self-describing persistence for JSON-serializable artifacts.

Every artifact written to disk carries a small envelope::

    {"schema": "<name>", "schema_version": <int>, "payload": {...}}

:func:`parse_envelope` refuses to load an envelope whose schema name or
version it does not recognize, so a stale file can never be silently
mis-read as a newer layout. Envelope bytes are produced with sorted keys
and compact separators, so identical logical content hashes identically
across runs and machines — the property golden fixtures rely on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CURRENT_VERSION = 1


class PersistError(ValueError):
    """Raised when a persisted envelope is malformed, unknown, or mismatched."""


def wrap_envelope(
    schema: str,
    payload: dict[str, Any],
    *,
    version: int = CURRENT_VERSION,
) -> dict[str, Any]:
    """Build the envelope dict (no serialization) for ``payload``."""
    return {"schema": schema, "schema_version": version, "payload": payload}


def dump_envelope(
    schema: str,
    payload: dict[str, Any],
    *,
    version: int = CURRENT_VERSION,
) -> str:
    """Serialize ``payload`` into canonical envelope bytes."""
    envelope = wrap_envelope(schema, payload, version=version)
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def parse_envelope(
    text: str,
    schema: str,
    *,
    version: int = CURRENT_VERSION,
) -> dict[str, Any]:
    """Validate envelope ``text`` and return its payload.

    Raises :class:`PersistError` when the text is not JSON, is not an
    object, names a different schema, carries an unexpected version, or
    holds a non-object payload.
    """
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PersistError(f"malformed JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise PersistError("envelope is not a JSON object")
    found_schema = envelope.get("schema")
    if found_schema != schema:
        raise PersistError(f"schema mismatch: expected {schema!r}, got {found_schema!r}")
    found_version = envelope.get("schema_version")
    if found_version != version:
        raise PersistError(
            f"unsupported schema_version for {schema!r}: {found_version!r} (want {version})"
        )
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise PersistError("payload is not a JSON object")
    return payload


def write_envelope(
    path: str | Path,
    schema: str,
    payload: dict[str, Any],
    *,
    version: int = CURRENT_VERSION,
) -> None:
    """Write ``payload`` to ``path`` as canonical envelope bytes."""
    Path(path).write_text(dump_envelope(schema, payload, version=version), encoding="utf-8")


def read_envelope(
    path: str | Path,
    schema: str,
    *,
    version: int = CURRENT_VERSION,
) -> dict[str, Any]:
    """Read and validate the envelope stored at ``path``."""
    return parse_envelope(Path(path).read_text(encoding="utf-8"), schema, version=version)
