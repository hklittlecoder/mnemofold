"""Canonical JSON helpers shared by every checksummed artifact.

Graph checksums, playbook digests, plan digests and report digests all
need byte-stable JSON: sorted keys, compact separators and an explicit
ASCII policy. Keeping one implementation guarantees digests stay
comparable across modules and gives golden tests a single place to pin
behavior against.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any, *, ensure_ascii: bool = True) -> str:
    """Serialize ``obj`` to byte-stable canonical JSON text.

    Keys are sorted, separators are compact and non-ASCII characters are
    escaped by default. Graph artifacts historically keep UTF-8 text
    verbatim (``ensure_ascii=False``); the keyword preserves that
    distinction so no existing digest changes value.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_ascii)


def sha256_hex(obj: Any, *, ensure_ascii: bool = True) -> str:
    """SHA-256 hex digest of the canonical JSON form of ``obj``."""
    payload = canonical_json(obj, ensure_ascii=ensure_ascii)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
