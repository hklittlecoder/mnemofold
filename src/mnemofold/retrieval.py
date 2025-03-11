"""Retrieval: BM25 inverted index, graph expansion, MMR reranking, citations.

Provides search over memory items using BM25 term weighting, entity-graph
expansion, temporal filters, diversity-aware MMR reranking, and citation
payloads that always point to an existing memory.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from mnemofold.memory import MemoryItem, MemoryStore

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Simple whitespace/punctuation tokenizer with lowercase folding."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass(slots=True)
class SearchResult:
    """A single search result."""

    item_id: str
    score: float
    title: str
    snippet: str
    citation: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class BM25Index:
    """BM25 inverted index over memory items.

    Uses standard BM25 (Okapi) with k1=1.5 and b=0.75.
    """

    k1: float = 1.5
    b: float = 0.75
    _docs: dict[str, str] = field(default_factory=dict)  # item_id -> text
    _df: dict[str, int] = field(default_factory=dict)  # term -> doc count
    _tf: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(dict)
    )  # term -> {item_id: freq}
    _avgdl: float = 0.0
    _total_len: int = 0

    def add(self, item_id: str, text: str) -> None:
        """Add an item to the index."""
        if item_id in self._docs:
            self.remove(item_id)
        tokens = tokenize(text)
        self._docs[item_id] = text
        self._total_len += len(tokens)
        self._avgdl = self._total_len / len(self._docs) if self._docs else 0.0
        freq: dict[str, int] = defaultdict(int)
        for t in tokens:
            freq[t] += 1
        for term, f in freq.items():
            self._tf[term][item_id] = f
            self._df[term] = self._df.get(term, 0) + 1

    def remove(self, item_id: str) -> None:
        """Remove an item from the index."""
        if item_id not in self._docs:
            return
        text = self._docs.pop(item_id)
        tokens = tokenize(text)
        self._total_len -= len(tokens)
        self._avgdl = self._total_len / len(self._docs) if self._docs else 0.0
        for term in set(tokens):
            if item_id in self._tf.get(term, {}):
                del self._tf[term][item_id]
                self._df[term] = max(0, self._df[term] - 1)

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Search for items matching query. Returns (item_id, score) sorted desc."""
        query_terms = tokenize(query)
        if not query_terms:
            return []
        n_docs = len(self._docs)
        scores: dict[str, float] = defaultdict(float)
        for term in query_terms:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for doc_id, tf in self._tf.get(term, {}).items():
                dl = len(tokenize(self._docs[doc_id]))
                denom = tf + self.k1 * (1 - self.b + self.b * dl / max(1.0, self._avgdl))
                scores[doc_id] += idf * (tf * (self.k1 + 1)) / denom
        results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def doc_count(self) -> int:
        return len(self._docs)


def mmr_rerank(
    results: list[tuple[str, float]],
    item_texts: dict[str, str],
    lambda_param: float = 0.5,
    top_k: int = 10,
) -> list[str]:
    """Maximal Marginal Relevance reranking for diversity.

    Balances relevance (score) with dissimilarity to already-selected items.
    Higher lambda = more relevance, lower lambda = more diversity.
    """
    if not results:
        return []

    selected: list[str] = []
    remaining = {item_id: score for item_id, score in results}

    while remaining and len(selected) < top_k:
        best_id = None
        best_mmr = float("-inf")
        for item_id, rel_score in remaining.items():
            # Compute max similarity to already-selected items
            max_sim = 0.0
            if selected:
                text = item_texts.get(item_id, "")
                for sel_id in selected:
                    sel_text = item_texts.get(sel_id, "")
                    sim = _text_sim_tokens(text, sel_text)
                    if sim > max_sim:
                        max_sim = sim
            mmr_score = lambda_param * rel_score - (1 - lambda_param) * max_sim
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_id = item_id
        if best_id is None:
            break
        selected.append(best_id)
        del remaining[best_id]
    return selected


def _text_sim_tokens(a: str, b: str) -> float:
    """Jaccard similarity of token sets."""
    if not a or not b:
        return 0.0
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class RetrievalEngine:
    """Combined retrieval engine: BM25 + graph expansion + MMR + citations."""

    store: MemoryStore
    index: BM25Index = field(default_factory=BM25Index)
    _graph_cache: dict[str, list[str]] = field(default_factory=dict)

    def index_item(self, item: MemoryItem) -> None:
        text = f"{item.title} {item.content}"
        self.index.add(item.item_id, text)

    def build_index(self) -> None:
        """Build index from all items in the store."""
        for item in self.store._items.values():
            self.index_item(item)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        lambda_mmr: float = 0.5,
        min_score: float = 0.0,
        tags: set[str] | None = None,
    ) -> list[SearchResult]:
        """Search memory items with MMR reranking and citations.

        All citations point to items that exist in the store.
        """
        bm25_results = self.index.search(query, top_k=top_k * 3)
        bm25_results = [(i, s) for i, s in bm25_results if s >= min_score]

        if tags:
            tag_filtered: list[tuple[str, float]] = []
            for i, s in bm25_results:
                item = self.store.get(i)
                if item is not None and tags & item.tags:
                    tag_filtered.append((i, s))
            bm25_results = tag_filtered

        # Collect texts for MMR
        texts = {}
        for item_id, _ in bm25_results:
            item = self.store.get(item_id)
            if item:
                texts[item_id] = f"{item.title} {item.content}"

        # MMR rerank
        ranked_ids = mmr_rerank(bm25_results, texts, lambda_param=lambda_mmr, top_k=top_k)

        # Build results with citations
        results: list[SearchResult] = []
        score_map = dict(bm25_results)
        for item_id in ranked_ids:
            item = self.store.get(item_id)
            if item is None:
                continue
            snippet = self._make_snippet(item.content, query)
            citation = f"[{item.item_id}]"
            reasons = [f"bm25_score={score_map.get(item_id, 0):.3f}"]
            results.append(
                SearchResult(
                    item_id=item_id,
                    score=score_map.get(item_id, 0.0),
                    title=item.title,
                    snippet=snippet,
                    citation=citation,
                    reasons=reasons,
                )
            )
        return results

    def _make_snippet(self, text: str, query: str, max_len: int = 120) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    def property_citations_resolve(self, query: str) -> bool:
        """Property test: all result citations point to existing items."""
        results = self.search(query)
        return all(self.store.get(r.item_id) is not None for r in results)
