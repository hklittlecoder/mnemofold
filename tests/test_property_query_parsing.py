"""Randomized query strings: parsing invariants that must always hold.

Over seeded shuffles of filter tokens, negations and free words:
to_dict/from_dict roundtrips exactly, filter syntax never leaks into
the free-text part, exclusions never carry the leading dash, and
parsing is deterministic.
"""

import random

from mnemofold.retrieval import ParsedQuery, parse_query

TOKENS = [
    "tag:alpha",
    "tag:Beta",
    "person:ana",
    "project:atlas",
    "before:2026-01-01",
    "after:2025-06-30",
    "on:2025-12-24",
    "-tag:draft",
    "-person:bo",
    "-project:ops",
    "-budget",
    "-Release",
    "release",
    "notes",
    "q3-plan",
]


def random_query(seed: int) -> str:
    rng = random.Random(seed)
    return " ".join(rng.sample(TOKENS, rng.randint(1, len(TOKENS))))


class TestQueryFuzz:
    def test_roundtrip_is_lossless(self):
        for seed in range(200):
            raw = random_query(seed)
            parsed = parse_query(raw)
            assert ParsedQuery.from_dict(parsed.to_dict()) == parsed, raw

    def test_filter_syntax_never_leaks_into_text(self):
        for seed in range(200):
            parsed = parse_query(random_query(seed))
            for prefix in ("tag:", "person:", "project:", "before:", "after:", "on:"):
                assert prefix not in parsed.text.lower(), (seed, parsed.text)

    def test_exclusions_have_no_leading_dash(self):
        for seed in range(200):
            parsed = parse_query(random_query(seed))
            for term in parsed.excluded_terms:
                assert not term.startswith("-"), (seed, term)
            for tag in parsed.excluded_tags:
                assert not tag.startswith("-"), (seed, tag)

    def test_parsing_is_deterministic(self):
        for seed in range(100):
            raw = random_query(seed)
            assert parse_query(raw).to_dict() == parse_query(raw).to_dict(), raw

    def test_hyphenated_words_survive_as_text(self):
        for seed in range(200):
            raw = random_query(seed)
            if "q3-plan" in raw.split():
                assert "q3-plan" in parse_query(raw).text.split()
