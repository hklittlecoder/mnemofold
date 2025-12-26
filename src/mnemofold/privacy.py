"""Privacy and policy engine for mnemofold.

Provides PII detection with pattern-based detectors (email, phone,
credit-card with Luhn check, address fragments), reversible and
irreversible redaction, tier-based access rules, an immutable access
log, and a declarative allow/deny/ask policy engine with precedence
and conflict diagnostics.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from mnemofold.persist import read_envelope, write_envelope

REDACTION_VAULT_SCHEMA = "redaction_vault"
REDACTION_VAULT_VERSION = 1


class PiiKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    CREDIT_CARD = "credit_card"
    ADDRESS = "address"
    NAME = "name"


class PrivacyTier(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RedactionMode(StrEnum):
    MASK = "mask"
    HASH = "hash"
    REMOVE = "remove"


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(slots=True, frozen=True)
class PiiMatch:
    kind: PiiKind
    start: int
    end: int
    value: str


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
_CC_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_ADDRESS_RE = re.compile(
    r"\b\d+\s+[A-Za-z][A-Za-z0-9\s\-]{0,40}\s+(?:street|st\.?|avenue|ave\.?|road|rd\.?|boulevard|blvd\.?|drive|dr\.?|lane|ln\.?|court|ct\.?|place|pl\.?|way|parkway|pkwy\.?)\b",
    re.IGNORECASE,
)
# Names are only detected behind explicit cues (a salutation or a
# signature line) so ordinary sentence-initial capitals never match.
_SALUTATION_RE = re.compile(
    r"\b(?:Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.)\s+"
    r"(?P<name>[A-Z][A-Za-z'\-]*(?:\s+[A-Z][A-Za-z'\-]*){0,2})"
)
_SIGNATURE_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:--|Regards,|Best,|Signed,|Thanks,)[ \t]*\n[ \t]*"
    r"(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})[ \t]*(?:\n|$)"
)


def _luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect_pii(text: str) -> list[PiiMatch]:
    """Return all PII matches found in text, sorted by start position.

    Credit-card candidates are validated with the Luhn checksum before
    being reported.  Overlapping matches are kept; callers can filter.
    """
    matches: list[PiiMatch] = []

    for m in _EMAIL_RE.finditer(text):
        matches.append(PiiMatch(PiiKind.EMAIL, m.start(), m.end(), m.group()))

    for m in _PHONE_RE.finditer(text):
        val = m.group().strip()
        digits = sum(1 for c in val if c.isdigit())
        if digits >= 10:
            matches.append(PiiMatch(PiiKind.PHONE, m.start(), m.end(), val))

    for m in _CC_RE.finditer(text):
        val = m.group()
        if _luhn_valid(val):
            matches.append(PiiMatch(PiiKind.CREDIT_CARD, m.start(), m.end(), val))

    for m in _ADDRESS_RE.finditer(text):
        matches.append(PiiMatch(PiiKind.ADDRESS, m.start(), m.end(), m.group().strip()))

    for regex in (_SALUTATION_RE, _SIGNATURE_RE):
        for m in regex.finditer(text):
            name = m.group("name").strip()
            start = m.start("name")
            matches.append(PiiMatch(PiiKind.NAME, start, start + len(name), name))

    matches.sort(key=lambda x: (x.start, x.end))
    return matches


def redact(
    text: str,
    matches: list[PiiMatch],
    mode: RedactionMode = RedactionMode.MASK,
    hash_salt: str = "",
) -> str:
    """Redact matched PII spans from text.

    MASK replaces each match with ``[<kind>]``.  HASH replaces with a
    stable SHA-256 hex prefix (so the same value + salt maps to the
    same token).  REMOVE deletes the span entirely.
    """
    if not matches:
        return text
    # Sort by start desc to preserve offsets while replacing
    sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
    result = text
    for m in sorted_matches:
        if mode == RedactionMode.MASK:
            replacement = f"[{m.kind.value}]"
        elif mode == RedactionMode.HASH:
            digest = hashlib.sha256((hash_salt + m.value).encode()).hexdigest()[:16]
            replacement = f"<pii:{m.kind.value}:{digest}>"
        else:  # REMOVE
            replacement = ""
        result = result[: m.start] + replacement + result[m.end :]
    return result


@dataclass(slots=True)
class PolicyRule:
    """A single access-policy rule."""

    rule_id: str
    effect: PolicyEffect
    action: str
    resource_tier: PrivacyTier | None = None
    principal: str | None = None
    precedence: int = 100


@dataclass(slots=True)
class PolicyDecision:
    effect: PolicyEffect
    matched_rules: list[str]
    conflicts: list[str] = field(default_factory=list)


class PolicyEngine:
    """Declarative allow/deny/ask policy with precedence and conflict detection.

    Rules are evaluated in precedence order (lowest number = highest
    precedence).  The first matching rule wins, but when rules at the
    same precedence level conflict, a conflict diagnostic is recorded
    and the effect falls back to ``ASK``.
    """

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules: list[PolicyRule] = list(rules or [])

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)

    def rules(self) -> list[PolicyRule]:
        return list(self._rules)

    def explain(
        self,
        action: str,
        principal: str,
        resource_tier: PrivacyTier,
    ) -> list[dict[str, Any]]:
        """Rule-by-rule audit trail for one decision.

        Every configured rule gets one entry, in declaration order:
        whether it matched and, when it did not, which predicate
        (action / principal / tier) excluded it. Denials and ASK
        fallbacks can therefore always be traced back to concrete rules.
        """
        trail: list[dict[str, Any]] = []
        for rule in self._rules:
            if rule.action != "*" and rule.action != action:
                trail.append(
                    {
                        "rule_id": rule.rule_id,
                        "matched": False,
                        "reason": f"action != {rule.action}",
                    }
                )
                continue
            if rule.principal is not None and rule.principal != principal:
                trail.append(
                    {
                        "rule_id": rule.rule_id,
                        "matched": False,
                        "reason": f"principal != {rule.principal}",
                    }
                )
                continue
            if rule.resource_tier is not None and rule.resource_tier != resource_tier:
                trail.append(
                    {
                        "rule_id": rule.rule_id,
                        "matched": False,
                        "reason": f"tier != {rule.resource_tier.value}",
                    }
                )
                continue
            trail.append(
                {
                    "rule_id": rule.rule_id,
                    "matched": True,
                    "reason": f"effect={rule.effect.value} precedence={rule.precedence}",
                }
            )
        return trail

    def evaluate(
        self,
        action: str,
        principal: str,
        resource_tier: PrivacyTier,
    ) -> PolicyDecision:
        matched: list[PolicyRule] = []
        for rule in self._rules:
            if rule.action != "*" and rule.action != action:
                continue
            if rule.principal is not None and rule.principal != principal:
                continue
            if rule.resource_tier is not None and rule.resource_tier != resource_tier:
                continue
            matched.append(rule)

        if not matched:
            return PolicyDecision(effect=PolicyEffect.DENY, matched_rules=["implicit-deny"])

        matched.sort(key=lambda r: r.precedence)
        top_precedence = matched[0].precedence
        top_rules = [r for r in matched if r.precedence == top_precedence]
        effects = {r.effect for r in top_rules}

        if len(effects) == 1:
            return PolicyDecision(
                effect=next(iter(effects)),
                matched_rules=[r.rule_id for r in top_rules],
            )

        return PolicyDecision(
            effect=PolicyEffect.ASK,
            matched_rules=[r.rule_id for r in top_rules],
            conflicts=[
                f"conflicting effects at precedence {top_precedence}: {sorted(e.value for e in effects)}"
            ],
        )


@dataclass(slots=True)
class AccessLogEntry:
    timestamp: datetime
    principal: str
    action: str
    resource_id: str
    granted: bool
    reason: str


def _entry_payload(entry: AccessLogEntry) -> str:
    """Canonical, deterministic serialization of one access-log entry."""
    return "|".join(
        [
            entry.timestamp.isoformat(),
            entry.principal,
            entry.action,
            entry.resource_id,
            "1" if entry.granted else "0",
            entry.reason,
        ]
    )


class AccessLog:
    """Append-only, hash-chained access log.

    Each entry is chained to its predecessor with SHA-256, so editing,
    reordering, or dropping a recorded entry is detected by
    :meth:`verify`. The log itself never mutates an entry in place.
    """

    _GENESIS = "0" * 64

    def __init__(self) -> None:
        self._entries: list[AccessLogEntry] = []
        self._hashes: list[str] = []

    def record(self, entry: AccessLogEntry) -> str:
        """Append an entry, chaining it to the current head. Returns its hash."""
        prev = self._hashes[-1] if self._hashes else self._GENESIS
        digest = hashlib.sha256((prev + "\n" + _entry_payload(entry)).encode()).hexdigest()
        self._entries.append(entry)
        self._hashes.append(digest)
        return digest

    def entries(self) -> list[AccessLogEntry]:
        return list(self._entries)

    def head_hash(self) -> str:
        return self._hashes[-1] if self._hashes else self._GENESIS

    def verify(self) -> bool:
        """Recompute the chain and confirm it matches the stored hashes."""
        prev = self._GENESIS
        for entry, stored in zip(self._entries, self._hashes, strict=True):
            expected = hashlib.sha256((prev + "\n" + _entry_payload(entry)).encode()).hexdigest()
            if expected != stored:
                return False
            prev = stored
        return True

    def count_by_principal(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entries:
            counts[e.principal] = counts.get(e.principal, 0) + 1
        return counts


_TIER_ORDER = {
    PrivacyTier.PUBLIC: 0,
    PrivacyTier.INTERNAL: 1,
    PrivacyTier.CONFIDENTIAL: 2,
    PrivacyTier.RESTRICTED: 3,
}


def can_read(consumer_tier: PrivacyTier, resource_tier: PrivacyTier) -> bool:
    """Return True if a consumer at ``consumer_tier`` may read ``resource_tier``.

    Higher-numbered tiers can read lower-numbered ones (restricted can
    read confidential, but not the reverse).  Same-tier reads are
    always allowed.
    """
    return _TIER_ORDER[consumer_tier] >= _TIER_ORDER[resource_tier]


def can_write(actor_tier: PrivacyTier, resource_tier: PrivacyTier) -> bool:
    """Return True if an actor at ``actor_tier`` may write ``resource_tier``.

    An actor may only write content classified at or below its own tier:
    a PUBLIC actor cannot create RESTRICTED records, while a RESTRICTED
    actor may write anything down to PUBLIC.
    """
    return _TIER_ORDER[actor_tier] >= _TIER_ORDER[resource_tier]


def can_export(resource_tier: PrivacyTier, target_tier: PrivacyTier) -> bool:
    """Return True if content may move from ``resource_tier`` to ``target_tier``.

    Enforces the never-leak-downward invariant: a resource may be
    exported only into a context whose tier is at least as high as the
    resource's own classification. Exporting RESTRICTED content into a
    PUBLIC context is refused.
    """
    return _TIER_ORDER[target_tier] >= _TIER_ORDER[resource_tier]


def export_violations(resource_tier: PrivacyTier, target_tier: PrivacyTier) -> list[str]:
    """Human-readable reasons an export would leak; empty when allowed."""
    if can_export(resource_tier, target_tier):
        return []
    return [f"cannot export {resource_tier.value} content to lower tier {target_tier.value}"]


def _select_non_overlapping(matches: list[PiiMatch]) -> list[PiiMatch]:
    """Greedily keep leftmost-longest matches, dropping overlaps.

    Reversible sealing rewrites spans in place, so overlapping matches
    would corrupt offsets. This yields a disjoint set in document order.
    """
    chosen: list[PiiMatch] = []
    for m in sorted(matches, key=lambda x: (x.start, -(x.end - x.start))):
        if chosen and m.start < chosen[-1].end:
            continue
        chosen.append(m)
    return chosen


@dataclass(slots=True)
class RedactionVault:
    """Reversible redaction: seals PII into tokens, unseals back to originals.

    ``seal`` replaces each detected PII span with a stable token
    ``<sealed:kind:digest>`` derived from ``salt + value`` (so the same
    value maps to one token across a document, keeping cross-references
    consistent without leaking the value). The vault remembers
    token -> original; ``unseal`` restores it. A vault is the only holder
    of the mapping, so sealed text can be shared while the vault stays
    private. Deterministic for a fixed salt.
    """

    salt: str = ""
    _token_to_value: dict[str, str] = field(default_factory=dict)

    def _token(self, kind: str, value: str) -> str:
        digest = hashlib.sha256((self.salt + value).encode()).hexdigest()[:16]
        token = f"<sealed:{kind}:{digest}>"
        self._token_to_value[token] = value
        return token

    def seal(self, text: str) -> str:
        matches = _select_non_overlapping(detect_pii(text))
        result = text
        for m in reversed(matches):  # reverse keeps earlier offsets valid
            token = self._token(m.kind.value, m.value)
            result = result[: m.start] + token + result[m.end :]
        return result

    def unseal(self, text: str) -> str:
        result = text
        for token in sorted(self._token_to_value, key=len, reverse=True):
            result = result.replace(token, self._token_to_value[token])
        return result

    def sealed_count(self) -> int:
        return len(self._token_to_value)

    def known_tokens(self) -> list[str]:
        return sorted(self._token_to_value)

    def to_dict(self) -> dict[str, Any]:
        """Serializable form: the salt plus the token -> value map.

        The vault is the sole private holder of the mapping, so this
        payload is exactly as sensitive as the originals it protects and
        must only be written to trusted storage. Round-tripping through
        :meth:`from_dict` restores the ability to unseal text sealed by
        this vault.
        """
        return {"salt": self.salt, "tokens": dict(self._token_to_value)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedactionVault:
        """Rebuild a vault from :meth:`to_dict` output."""
        vault = cls(salt=data.get("salt", ""))
        vault._token_to_value = dict(data.get("tokens", {}))
        return vault

    def save(self, path: str | Path) -> None:
        """Write the vault to ``path`` as a versioned envelope."""
        write_envelope(
            path, REDACTION_VAULT_SCHEMA, self.to_dict(), version=REDACTION_VAULT_VERSION
        )

    @classmethod
    def load(cls, path: str | Path) -> RedactionVault:
        """Load a vault written by :meth:`save`."""
        data = read_envelope(path, REDACTION_VAULT_SCHEMA, version=REDACTION_VAULT_VERSION)
        return cls.from_dict(data)
