"""Negated filters and excluded terms in the query grammar."""

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import ParsedQuery, RetrievalEngine, parse_query


def item(item_id: str, text: str, *, tags=(), project: str = "", people=()) -> MemoryItem:
    metadata: dict = {}
    if project:
        metadata["project"] = project
    if people:
        metadata["people"] = list(people)
    return MemoryItem(
        item_id=item_id,
        tier=MemoryTier.SEMANTIC,
        content=text,
        title=text,
        tags=set(tags),
        metadata=metadata,
        created_at="2026-03-01T09:00:00+00:00",
    )


def make_engine() -> RetrievalEngine:
    store = MemoryStore()
    store.add(
        item("m1", "release plan for atlas", tags={"release"}, project="atlas", people=["ana"])
    )
    store.add(item("m2", "release notes draft", tags={"release", "draft"}, project="atlas"))
    store.add(item("m3", "budget review notes", tags={"finance"}, project="ops", people=["bo"]))
    engine = RetrievalEngine(store=store)
    engine.build_index()
    return engine


class TestParseNegation:
    def test_negated_tag(self):
        parsed = parse_query("release -tag:draft")
        assert parsed.text == "release"
        assert parsed.excluded_tags == ["draft"]

    def test_negated_person_and_project(self):
        parsed = parse_query("-person:bo -project:ops notes")
        assert parsed.excluded_people == ["bo"]
        assert parsed.excluded_projects == ["ops"]
        assert parsed.text == "notes"

    def test_bare_negated_term(self):
        parsed = parse_query("release -budget")
        assert parsed.excluded_terms == ["budget"]
        assert parsed.text == "release"

    def test_negation_is_case_folded(self):
        parsed = parse_query("-tag:Draft -DRAFT")
        assert parsed.excluded_tags == ["draft"]
        assert parsed.excluded_terms == ["draft"]

    def test_hyphenated_words_are_not_negations(self):
        parsed = parse_query("e2e-tests -")
        assert parsed.text == "e2e-tests -"
        assert parsed.excluded_terms == []

    def test_roundtrip_preserves_negations(self):
        parsed = parse_query("plan -tag:draft -budget -person:bo")
        assert ParsedQuery.from_dict(parsed.to_dict()) == parsed

    def test_has_filters_sees_negations(self):
        assert parse_query("-tag:x").has_filters()
        assert parse_query("-word").has_filters()
        assert not parse_query("plain text").has_filters()


class TestSearchNegation:
    def test_excluded_tag_drops_match(self):
        engine = make_engine()
        results = engine.search_parsed(parse_query("release -tag:draft"))
        assert [r.item_id for r in results] == ["m1"]

    def test_excluded_term_drops_match(self):
        engine = make_engine()
        results = engine.search_parsed(parse_query("notes -budget"))
        assert {r.item_id for r in results} == {"m2"}

    def test_excluded_person_and_project(self):
        engine = make_engine()
        results = engine.search_parsed(parse_query("notes -person:bo"))
        assert all(r.item_id != "m3" for r in results)
        results = engine.search_parsed(parse_query("notes -project:ops"))
        assert all(r.item_id != "m3" for r in results)

    def test_filter_only_negation_query(self):
        engine = make_engine()
        results = engine.search_parsed(parse_query("-tag:release"))
        assert [r.item_id for r in results] == ["m3"]

    def test_positive_and_negative_combine(self):
        engine = make_engine()
        results = engine.search_parsed(parse_query("tag:release -tag:draft release"))
        assert [r.item_id for r in results] == ["m1"]
