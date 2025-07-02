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


class AccessLog:
    """Append-only access log.  Entries cannot be modified once added."""

    def __init__(self) -> None:
        self._entries: list[AccessLogEntry] = []

    def record(self, entry: AccessLogEntry) -> None:
        self._entries.append(entry)

    def entries(self) -> list[AccessLogEntry]:
        return list(self._entries)

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
