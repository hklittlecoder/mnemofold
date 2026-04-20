"""Corner cases: self-cancellation, dedupe, ordering, workspace passthrough."""

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import RetrievalEngine, parse_query


def make_engine() -> RetrievalEngine:
    store = MemoryStore()
    store.add(
        MemoryItem(
            item_id="m1",
            tier=MemoryTier.SEMANTIC,
            content="alpha beta",
            title="alpha beta",
            tags={"x"},
            created_at="2026-03-01T09:00:00+00:00",
        )
    )
    engine = RetrievalEngine(store=store)
    engine.build_index()
    return engine


class TestNegationEdges:
    def test_self_cancellation_yields_nothing(self):
        parsed = parse_query("tag:x -tag:x")
        engine = make_engine()
        assert engine.search_parsed(parsed) == []

    def test_duplicate_negations_dedupe(self):
        parsed = parse_query("-tag:a -tag:a -word -word")
        assert parsed.excluded_tags == ["a"]
        assert parsed.excluded_terms == ["word"]

    def test_negation_only_query_has_no_text(self):
        parsed = parse_query("-tag:draft")
        assert parsed.text == ""
        assert parsed.excluded_tags == ["draft"]

    def test_exclusion_of_everything_returns_empty(self):
        engine = make_engine()
        assert engine.search_parsed(parse_query("-alpha")) == []

    def test_negative_instant_filter_stays_text(self):
        parsed = parse_query("-before:2026-01-01")
        assert parsed.before is None
        # -before:... is not a recognized negation; it becomes an excluded
        # term rather than silently acting as a positive temporal filter
        assert parsed.excluded_terms == ["before:2026-01-01"]

    def test_workspace_ask_honors_negation(self, tmp_path):
        from mnemofold.workspace import Workspace

        ws = Workspace(tmp_path / "ws")
        ws.remember(
            "release budget numbers",
            title="budget note",
            tags=["finance"],
            now="2026-03-01T09:00:00+00:00",
        )
        ws.remember(
            "release plan outline",
            title="plan note",
            tags=["release"],
            now="2026-03-01T09:10:00+00:00",
        )
        budget_id = next(h.item_id for h in ws.ask("budget"))
        assert budget_id in {h.item_id for h in ws.ask("release")}
        assert budget_id not in {h.item_id for h in ws.ask("release -budget")}
        ws.close()
