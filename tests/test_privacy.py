from datetime import UTC, datetime

from mnemofold.privacy import (
    AccessLog,
    AccessLogEntry,
    PiiKind,
    PolicyEffect,
    PolicyEngine,
    PolicyRule,
    PrivacyTier,
    RedactionMode,
    RedactionVault,
    can_read,
    detect_pii,
    redact,
)


def test_detect_email():
    text = "Contact me at alice@example.com please."
    matches = detect_pii(text)
    assert any(m.kind == PiiKind.EMAIL and m.value == "alice@example.com" for m in matches)


def test_detect_phone():
    text = "Call (415) 555-0123 for details."
    matches = detect_pii(text)
    phones = [m for m in matches if m.kind == PiiKind.PHONE]
    assert len(phones) >= 1


def test_detect_credit_card_valid_luhn():
    # 4532015112830366 is a valid Luhn test number
    text = "Card: 4532015112830366."
    matches = detect_pii(text)
    cards = [m for m in matches if m.kind == PiiKind.CREDIT_CARD]
    assert len(cards) >= 1


def test_detect_credit_card_invalid_luhn_rejected():
    text = "Card: 1234567890123456."
    matches = detect_pii(text)
    cards = [m for m in matches if m.kind == PiiKind.CREDIT_CARD]
    assert len(cards) == 0


def test_detect_address():
    text = "Ship to 123 Main Street, Springfield, IL."
    matches = detect_pii(text)
    addresses = [m for m in matches if m.kind == PiiKind.ADDRESS]
    assert len(addresses) >= 1


def test_detect_pii_sorted_by_position():
    text = "Email a@b.co and call 415-555-0199 please."
    matches = detect_pii(text)
    starts = [m.start for m in matches]
    assert starts == sorted(starts)


def test_detect_pii_empty_text():
    assert detect_pii("") == []
    assert detect_pii("nothing sensitive here") == []


def test_redact_mask():
    text = "Email alice@example.com please."
    matches = detect_pii(text)
    result = redact(text, matches, mode=RedactionMode.MASK)
    assert "alice@example.com" not in result
    assert "[email]" in result


def test_redact_hash_stable():
    text = "user1@example.com and user1@example.com"
    matches = detect_pii(text)
    r1 = redact(text, matches, mode=RedactionMode.HASH, hash_salt="s1")
    r2 = redact(text, matches, mode=RedactionMode.HASH, hash_salt="s1")
    assert r1 == r2
    assert "user1@example.com" not in r1


def test_redact_hash_different_salt():
    text = "alice@example.com"
    matches = detect_pii(text)
    r1 = redact(text, matches, mode=RedactionMode.HASH, hash_salt="a")
    r2 = redact(text, matches, mode=RedactionMode.HASH, hash_salt="b")
    assert r1 != r2


def test_redact_remove():
    text = "X alice@example.com Y"
    matches = detect_pii(text)
    result = redact(text, matches, mode=RedactionMode.REMOVE)
    assert "alice@example.com" not in result
    assert "X  Y" in result or "X Y" in result


def test_redact_no_matches_is_identity():
    assert redact("hello world", []) == "hello world"


def test_redact_multiple_spans_preserve_order():
    text = "a@b.co then c@d.io end"
    matches = detect_pii(text)
    result = redact(text, matches, mode=RedactionMode.MASK)
    assert result.count("[email]") == 2
    assert result.startswith("[email]")
    assert "then" in result


def test_can_read_same_tier():
    assert can_read(PrivacyTier.PUBLIC, PrivacyTier.PUBLIC)
    assert can_read(PrivacyTier.INTERNAL, PrivacyTier.INTERNAL)


def test_can_read_higher_can_read_lower():
    assert can_read(PrivacyTier.RESTRICTED, PrivacyTier.CONFIDENTIAL)
    assert can_read(PrivacyTier.CONFIDENTIAL, PrivacyTier.INTERNAL)
    assert can_read(PrivacyTier.INTERNAL, PrivacyTier.PUBLIC)


def test_can_read_lower_cannot_read_higher():
    assert not can_read(PrivacyTier.PUBLIC, PrivacyTier.INTERNAL)
    assert not can_read(PrivacyTier.INTERNAL, PrivacyTier.RESTRICTED)
    assert not can_read(PrivacyTier.CONFIDENTIAL, PrivacyTier.RESTRICTED)


def test_policy_engine_implicit_deny():
    engine = PolicyEngine()
    decision = engine.evaluate("read", "alice", PrivacyTier.INTERNAL)
    assert decision.effect == PolicyEffect.DENY
    assert "implicit-deny" in decision.matched_rules


def test_policy_engine_allow_rule():
    engine = PolicyEngine(
        [
            PolicyRule(rule_id="r1", effect=PolicyEffect.ALLOW, action="read", precedence=10),
        ]
    )
    decision = engine.evaluate("read", "anyone", PrivacyTier.PUBLIC)
    assert decision.effect == PolicyEffect.ALLOW
    assert decision.matched_rules == ["r1"]


def test_policy_engine_deny_overrides_lower_precedence():
    engine = PolicyEngine(
        [
            PolicyRule(
                rule_id="deny_restricted",
                effect=PolicyEffect.DENY,
                action="read",
                resource_tier=PrivacyTier.RESTRICTED,
                precedence=5,
            ),
            PolicyRule(
                rule_id="allow_all_read", effect=PolicyEffect.ALLOW, action="read", precedence=50
            ),
        ]
    )
    decision = engine.evaluate("read", "bob", PrivacyTier.RESTRICTED)
    assert decision.effect == PolicyEffect.DENY


def test_policy_engine_principal_filter():
    engine = PolicyEngine(
        [
            PolicyRule(
                rule_id="admin_all",
                effect=PolicyEffect.ALLOW,
                action="*",
                principal="admin",
                precedence=1,
            ),
        ]
    )
    assert engine.evaluate("read", "admin", PrivacyTier.PUBLIC).effect == PolicyEffect.ALLOW
    assert engine.evaluate("read", "user", PrivacyTier.PUBLIC).effect == PolicyEffect.DENY


def test_policy_engine_conflict_at_same_precedence():
    engine = PolicyEngine(
        [
            PolicyRule(rule_id="allow", effect=PolicyEffect.ALLOW, action="read", precedence=10),
            PolicyRule(rule_id="deny", effect=PolicyEffect.DENY, action="read", precedence=10),
        ]
    )
    decision = engine.evaluate("read", "alice", PrivacyTier.PUBLIC)
    assert decision.effect == PolicyEffect.ASK
    assert len(decision.conflicts) >= 1


def test_policy_engine_wildcard_action():
    engine = PolicyEngine(
        [
            PolicyRule(rule_id="any", effect=PolicyEffect.ALLOW, action="*", precedence=1),
        ]
    )
    assert engine.evaluate("read", "x", PrivacyTier.PUBLIC).effect == PolicyEffect.ALLOW
    assert engine.evaluate("write", "x", PrivacyTier.PUBLIC).effect == PolicyEffect.ALLOW


def test_access_log_append_only():
    log = AccessLog()
    entry = AccessLogEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        principal="alice",
        action="read",
        resource_id="mem-1",
        granted=True,
        reason="policy-allow",
    )
    log.record(entry)
    assert len(log.entries()) == 1
    assert log.entries()[0].principal == "alice"


def test_access_log_count_by_principal():
    log = AccessLog()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    log.record(AccessLogEntry(now, "alice", "read", "r1", True, ""))
    log.record(AccessLogEntry(now, "bob", "read", "r1", True, ""))
    log.record(AccessLogEntry(now, "alice", "write", "r2", False, ""))
    counts = log.count_by_principal()
    assert counts["alice"] == 2
    assert counts["bob"] == 1


class TestRedactionVault:
    TEXT = "Mail alice@example.com or call 555-123-4567 about the invoice."

    def test_seal_unseal_roundtrip(self):
        vault = RedactionVault(salt="s1")
        sealed = vault.seal(self.TEXT)
        assert "alice@example.com" not in sealed
        assert "555-123-4567" not in sealed
        assert vault.unseal(sealed) == self.TEXT

    def test_sealed_text_keeps_context(self):
        vault = RedactionVault(salt="s1")
        sealed = vault.seal(self.TEXT)
        assert "about the invoice" in sealed
        assert "<sealed:email:" in sealed
        assert "<sealed:phone:" in sealed

    def test_same_value_seals_to_one_token(self):
        vault = RedactionVault(salt="s1")
        sealed = vault.seal("a@b.com and again a@b.com")
        assert sealed.count("<sealed:email:") == 2
        assert vault.sealed_count() == 1  # one distinct value

    def test_salt_changes_tokens(self):
        one = RedactionVault(salt="one")
        two = RedactionVault(salt="two")
        assert one.seal(self.TEXT) != two.seal(self.TEXT)

    def test_seal_is_deterministic(self):
        assert RedactionVault(salt="s").seal(self.TEXT) == RedactionVault(salt="s").seal(self.TEXT)

    def test_text_without_pii_is_unchanged(self):
        vault = RedactionVault()
        plain = "nothing sensitive here"
        assert vault.seal(plain) == plain
        assert vault.sealed_count() == 0

    def test_unseal_ignores_unknown_tokens(self):
        vault = RedactionVault(salt="s")
        sealed = vault.seal(self.TEXT)
        other = RedactionVault(salt="s")
        assert other.unseal(sealed) == sealed  # other vault lacks the mapping

    def test_seal_unseal_multiple_documents_share_tokens(self):
        vault = RedactionVault(salt="s")
        first = vault.seal("ping alice@example.com")
        second = vault.seal("pong alice@example.com")
        token = vault.known_tokens()[0]
        assert token in first and token in second
        assert vault.unseal(second) == "pong alice@example.com"


class TestNameDetection:
    def test_salutation_cue(self):
        matches = detect_pii("Please contact Dr. Alice Zhang by Friday")
        names = [m for m in matches if m.kind == PiiKind.NAME]
        assert len(names) == 1
        assert names[0].value == "Alice Zhang"

    def test_all_salutations(self):
        for cue in ("Mr.", "Ms.", "Mrs.", "Dr.", "Prof."):
            matches = detect_pii(f"{cue} Bob Li replied")
            assert any(m.value == "Bob Li" for m in matches), cue

    def test_signature_block(self):
        text = "See attached draft.\nRegards,\nCarol Wu\n"
        matches = detect_pii(text)
        names = [m for m in matches if m.kind == PiiKind.NAME]
        assert [m.value for m in names] == ["Carol Wu"]

    def test_no_cue_no_name(self):
        matches = detect_pii("Alice went to the meeting with Bob")
        assert not [m for m in matches if m.kind == PiiKind.NAME]

    def test_name_span_points_at_name_only(self):
        text = "Ask Dr. Alice Zhang today"
        match = next(m for m in detect_pii(text) if m.kind == PiiKind.NAME)
        assert text[match.start : match.end] == "Alice Zhang"

    def test_names_are_masked_and_sealed(self):
        text = "cc Dr. Alice Zhang"
        masked = redact(text, detect_pii(text), mode=RedactionMode.MASK)
        # the span covers the name only; the salutation stays visible
        assert masked == "cc Dr. [name]"
        vault = RedactionVault(salt="s")
        sealed = vault.seal(text)
        assert "<sealed:name:" in sealed
        assert vault.unseal(sealed) == text

    def test_matches_stay_sorted_with_names_included(self):
        text = "Mail alice@example.com, thanks.\nRegards,\nBob Li\n"
        matches = detect_pii(text)
        starts = [m.start for m in matches]
        assert starts == sorted(starts)
        kinds = {m.kind for m in matches}
        assert PiiKind.EMAIL in kinds and PiiKind.NAME in kinds


class TestPiiSweep:
    def test_overlapping_matches_are_deduped_by_vault(self):
        # An email contains a phone-like digit run in some corpora; sealing
        # must not corrupt offsets. Use adjacent PII to stress ordering.
        text = "Reach me at bob@x.io or 555-000-1111 soon."
        vault = RedactionVault(salt="s")
        sealed = vault.seal(text)
        assert vault.unseal(sealed) == text

    def test_mask_mode_uses_kind_labels(self):
        text = "card 4111 1111 1111 1111 on file"
        out = redact(text, detect_pii(text), mode=RedactionMode.MASK)
        assert "4111" not in out
        assert "[credit_card]" in out

    def test_remove_mode_deletes_span(self):
        text = "email: alice@example.com!"
        out = redact(text, detect_pii(text), mode=RedactionMode.REMOVE)
        assert "alice@example.com" not in out
        assert out == "email: !"

    def test_hash_mode_is_stable_per_salt(self):
        text = "bob@x.io"
        matches = detect_pii(text)
        a = redact(text, matches, mode=RedactionMode.HASH, hash_salt="s")
        b = redact(text, matches, mode=RedactionMode.HASH, hash_salt="s")
        c = redact(text, matches, mode=RedactionMode.HASH, hash_salt="other")
        assert a == b
        assert a != c

    def test_invalid_luhn_not_flagged_as_card(self):
        # 4111 1111 1111 1112 fails Luhn
        matches = detect_pii("card 4111 1111 1111 1112 here")
        assert not [m for m in matches if m.kind == PiiKind.CREDIT_CARD]

    def test_valid_luhn_flagged(self):
        matches = detect_pii("card 4111 1111 1111 1111 here")
        assert any(m.kind == PiiKind.CREDIT_CARD for m in matches)

    def test_short_digit_run_not_a_card(self):
        matches = detect_pii("order 12345 shipped")
        assert not [m for m in matches if m.kind == PiiKind.CREDIT_CARD]

    def test_address_detected(self):
        matches = detect_pii("Send to 1600 Pennsylvania Avenue")
        assert any(m.kind == PiiKind.ADDRESS for m in matches)

    def test_matches_sorted_by_position(self):
        text = "bob@x.io then 555-000-1111 then 12 Main Street"
        starts = [m.start for m in detect_pii(text)]
        assert starts == sorted(starts)

    def test_empty_text_no_matches(self):
        assert detect_pii("") == []

    def test_redact_without_matches_is_identity(self):
        assert redact("plain text", []) == "plain text"
