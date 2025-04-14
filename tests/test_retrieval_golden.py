"""Golden fixture pinning BM25 + MMR search output.

``fixtures/retrieval_search_golden.json`` records the ranked item ids,
quantized scores, and citations for a fixed corpus and query set. Any
change to tokenization, BM25 scoring, or MMR ordering makes this test
fail, so ranking drift is always deliberate and reviewable.
"""

import json
from pathlib import Path

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import RetrievalEngine

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "retrieval_search_golden.json"

CORPUS: tuple[tuple[str, str, str], ...] = (
    ("d1", "quarterly budget review with finance", "budget review"),
    ("d2", "budget planning session notes for the launch", "launch planning"),
    ("d3", "weekly engineering standup notes", "standup"),
    ("d4", "design doc for the parser rewrite", "design parser"),
    ("d5", "launch party playlist and catering", "launch party"),
    ("d6", "risk log update for the alpha milestone", "risk alpha"),
)

QUERIES: tuple[str, ...] = (
    "budget",
    "launch planning",
    "notes",
    "parser design doc",
    "alpha risk milestone",
)


def build_engine() -> RetrievalEngine:
    store = MemoryStore()
    engine = RetrievalEngine(store=store)
    for item_id, content, title in CORPUS:
        item = MemoryItem(item_id=item_id, tier=MemoryTier.SEMANTIC, content=content, title=title)
        store.add(item)
        engine.index_item(item)
    return engine


def golden_payload() -> str:
    payload: dict[str, list[dict[str, object]]] = {}
    for query in QUERIES:
        engine = build_engine()  # fresh engine per query: no cross-query state
        results = engine.search(query, top_k=4, lambda_mmr=0.7)
        payload[query] = [
            {"item_id": r.item_id, "score": round(r.score, 6), "citation": r.citation}
            for r in results
        ]
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class TestGoldenSearch:
    def test_ranking_matches_golden_fixture(self):
        assert GOLDEN_PATH.exists(), "golden fixture missing; regenerate it deliberately"
        assert golden_payload() == GOLDEN_PATH.read_text()

    def test_regeneration_is_stable(self):
        assert golden_payload() == golden_payload()

    def test_corpus_and_queries_nonempty(self):
        payload = json.loads(golden_payload())
        assert set(payload) == set(QUERIES)
        assert payload["budget"], "budget query must retrieve at least one doc"
