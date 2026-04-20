"""Retrieval: BM25 inverted index, graph expansion, MMR reranking, citations.

Provides search over memory items using BM25 term weighting, entity-graph
expansion, temporal filters, diversity-aware MMR reranking, and citation
payloads that always point to an existing memory.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemofold.deletion import DeletionEngine, DeletionReason, DeletionReport, GraphDeletionTarget
from mnemofold.graph import WorkstreamGraph
from mnemofold.memory import MemoryItem, MemoryStore
from mnemofold.persist import read_envelope, write_envelope

BM25_INDEX_SCHEMA = "bm25_index"
BM25_INDEX_VERSION = 1

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


@dataclass(slots=True, frozen=True)
class TermContribution:
    """One query term's BM25 contribution to a document score."""

    term: str
    tf: int
    df: int
    idf: float
    contribution: float


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
    _dl: dict[str, int] = field(default_factory=dict)  # item_id -> token count

    def add(self, item_id: str, text: str) -> None:
        """Add an item to the index."""
        if item_id in self._docs:
            self.remove(item_id)
        tokens = tokenize(text)
        self._docs[item_id] = text
        self._dl[item_id] = len(tokens)
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
        self._total_len -= self._dl.pop(item_id, 0)
        self._avgdl = self._total_len / len(self._docs) if self._docs else 0.0
        for term in set(tokenize(text)):
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
                dl = self._dl[doc_id]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / max(1.0, self._avgdl))
                scores[doc_id] += idf * (tf * (self.k1 + 1)) / denom
        results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def doc_count(self) -> int:
        return len(self._docs)

    def ids(self) -> list[str]:
        """All indexed item ids in deterministic (sorted) order."""
        return sorted(self._docs)

    def explain(self, query: str, item_id: str) -> list[TermContribution]:
        """Per-term BM25 contributions for one document.

        Mirrors :meth:`search` exactly — including double-counting a
        repeated query term — so the contributions always sum to the
        score search reports for ``item_id``. Terms absent from the
        corpus or from this document are skipped. Results are sorted by
        descending contribution with an alphabetical tie-break, making
        explanation payloads deterministic.
        """
        if item_id not in self._docs:
            return []
        query_terms = tokenize(query)
        if not query_terms:
            return []
        n_docs = len(self._docs)
        dl = self._dl[item_id]
        parts: list[TermContribution] = []
        for term in query_terms:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            tf = self._tf.get(term, {}).get(item_id, 0)
            if tf == 0:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + self.k1 * (1 - self.b + self.b * dl / max(1.0, self._avgdl))
            parts.append(
                TermContribution(
                    term=term,
                    tf=tf,
                    df=df,
                    idf=idf,
                    contribution=idf * (tf * (self.k1 + 1)) / denom,
                )
            )
        parts.sort(key=lambda p: (-p.contribution, p.term))
        return parts

    def to_dict(self) -> dict[str, Any]:
        """Serializable snapshot: ranking parameters plus the raw documents.

        The inverted-index internals (``_df``/``_tf``/``_avgdl``/``_dl``)
        are pure functions of the documents, so :meth:`from_dict`
        rebuilds them exactly by re-adding each document. Persisting only
        the documents keeps the payload small and the rebuild independent
        of the original insertion order.
        """
        return {
            "k1": self.k1,
            "b": self.b,
            "docs": {item_id: self._docs[item_id] for item_id in sorted(self._docs)},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BM25Index:
        """Rebuild an index from :meth:`to_dict` output."""
        index = cls(k1=float(data.get("k1", 1.5)), b=float(data.get("b", 0.75)))
        docs = data.get("docs", {})
        for item_id in sorted(docs):
            index.add(item_id, docs[item_id])
        return index

    def save(self, path: str | Path) -> None:
        """Write the index to ``path`` as a versioned envelope."""
        write_envelope(path, BM25_INDEX_SCHEMA, self.to_dict(), version=BM25_INDEX_VERSION)

    @classmethod
    def load(cls, path: str | Path) -> BM25Index:
        """Load an index written by :meth:`save`."""
        data = read_envelope(path, BM25_INDEX_SCHEMA, version=BM25_INDEX_VERSION)
        return cls.from_dict(data)


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
    graph: WorkstreamGraph | None = None
    _graph_cache: dict[str, list[str]] = field(default_factory=dict)
    _entity_index: dict[str, set[str]] = field(default_factory=dict)

    def index_item(self, item: MemoryItem) -> None:
        text = f"{item.title} {item.content}"
        self.index.add(item.item_id, text)
        for entity_id in sorted(str(e) for e in item.metadata.get("entity_ids", ())):
            self._entity_index.setdefault(entity_id, set()).add(item.item_id)

    def build_index(self) -> None:
        """Build index from all items in the store."""
        for item in self.store._items.values():
            self.index_item(item)

    def export_index(self) -> dict[str, Any]:
        """Snapshot the underlying BM25 index as a serializable dict.

        Lets a caller ship or persist the derived ranking structure
        without re-deriving it from the store on the other side.
        """
        return self.index.to_dict()

    def import_index(self, data: dict[str, Any]) -> None:
        """Replace the index with one rebuilt from :meth:`export_index` output."""
        self.index = BM25Index.from_dict(data)

    def save_index(self, path: str | Path) -> None:
        """Persist the index snapshot to ``path`` as a versioned envelope."""
        self.index.save(path)

    def load_index(self, path: str | Path) -> None:
        """Load an index snapshot written by :meth:`save_index`."""
        self.index = BM25Index.load(path)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        lambda_mmr: float = 0.5,
        min_score: float = 0.0,
        tags: set[str] | None = None,
        fusion: FusionWeights | None = None,
        now: str = "",
        expand_graph: bool = False,
        expansion_discount: float = 0.5,
        as_of: str = "",
    ) -> list[SearchResult]:
        """Search memory items with MMR reranking and citations.

        All citations point to items that exist in the store. When
        ``fusion`` is given, candidate scores are refolded from normalized
        relevance, item salience, and recency (see FusionWeights); ``now``
        (an ISO instant) is required whenever the recency weight is
        positive.
        """
        bm25_results = self.index.search(query, top_k=top_k * 3)
        bm25_results = [(i, s) for i, s in bm25_results if s >= min_score]

        extra_reasons: dict[str, list[str]] = {}
        if expand_graph and self.graph is not None:
            bm25_results = self._expand_with_graph(bm25_results, expansion_discount, extra_reasons)
        if as_of:
            bm25_results = self._apply_as_of(bm25_results, as_of)

        if tags:
            tag_filtered: list[tuple[str, float]] = []
            for i, s in bm25_results:
                item = self.store.get(i)
                if item is not None and tags & item.tags:
                    tag_filtered.append((i, s))
            bm25_results = tag_filtered

        if fusion is not None:
            bm25_results = self._apply_fusion(bm25_results, fusion, now, extra_reasons)

        return self._finalize(
            bm25_results,
            query,
            top_k=top_k,
            lambda_mmr=lambda_mmr,
            extra_reasons=extra_reasons,
        )

    def search_parsed(
        self,
        parsed: ParsedQuery,
        *,
        top_k: int = 10,
        lambda_mmr: float = 0.5,
        min_score: float = 0.0,
        fusion: FusionWeights | None = None,
        now: str = "",
        expand_graph: bool = False,
        expansion_discount: float = 0.5,
        as_of: str = "",
    ) -> list[SearchResult]:
        """Run a structured query: BM25 over the free text, plus filters.

        Filter semantics (all active filters must pass, i.e. AND):

        * ``tags``/``people`` intersect the item's tags / metadata people;
        * ``project`` matches the item's ``metadata["project"]``;
        * ``after`` is inclusive, ``before`` exclusive, ``on`` matches the
          UTC day of ``created_at``; undated items fail temporal filters;
        * unparseable temporal filter values are ignored.

        With empty free text the filters alone select candidates (each
        scoring 0.0), keeping filter-only queries deterministic.
        """
        if parsed.text:
            candidates = self.index.search(parsed.text, top_k=max(top_k * 3, 50))
            candidates = [(i, s) for i, s in candidates if s >= min_score]
        else:
            candidates = [(item_id, 0.0) for item_id in self.index.ids()]
        extra_reasons: dict[str, list[str]] = {}
        if expand_graph and self.graph is not None:
            candidates = self._expand_with_graph(candidates, expansion_discount, extra_reasons)
        if as_of:
            candidates = self._apply_as_of(candidates, as_of)
        if parsed.has_filters():
            candidates = [
                (item_id, score)
                for item_id, score in candidates
                if self._matches_filters(parsed, item_id)
            ]
        if fusion is not None:
            candidates = self._apply_fusion(candidates, fusion, now, extra_reasons)
        return self._finalize(
            candidates,
            parsed.text,
            top_k=top_k,
            lambda_mmr=lambda_mmr,
            extra_reasons=extra_reasons,
        )

    def _matches_filters(self, parsed: ParsedQuery, item_id: str) -> bool:
        item = self.store.get(item_id)
        if item is None:
            return False
        if parsed.tags:
            item_tags = {t.lower() for t in item.tags}
            if not item_tags.intersection(parsed.tags):
                return False
        if parsed.people:
            people = {str(p).lower() for p in item.metadata.get("people", ())}
            person = str(item.metadata.get("person", "")).lower()
            if person:
                people.add(person)
            if not people.intersection(parsed.people):
                return False
        if parsed.projects:
            project = str(item.metadata.get("project", "")).lower()
            if project not in parsed.projects:
                return False
        if parsed.excluded_tags:
            item_tags = {t.lower() for t in item.tags}
            if item_tags.intersection(parsed.excluded_tags):
                return False
        if parsed.excluded_people:
            people = {str(p).lower() for p in item.metadata.get("people", ())}
            person = str(item.metadata.get("person", "")).lower()
            if person:
                people.add(person)
            if people.intersection(parsed.excluded_people):
                return False
        if parsed.excluded_projects:
            project = str(item.metadata.get("project", "")).lower()
            if project in parsed.excluded_projects:
                return False
        if parsed.excluded_terms:
            words = set(tokenize(f"{item.title} {item.content}"))
            if any(term in words for term in parsed.excluded_terms):
                return False
        return self._within_time_bounds(parsed, item)

    def _within_time_bounds(self, parsed: ParsedQuery, item: MemoryItem) -> bool:
        if not (parsed.before or parsed.after or parsed.on):
            return True
        if not item.created_at:
            return False  # undated items fail explicit temporal filters
        created = _parse_filter_instant(item.created_at)
        if created is None:
            return False
        if parsed.before is not None:
            bound = _parse_filter_instant(parsed.before)
            if bound is not None and created >= bound:
                return False
        if parsed.after is not None:
            bound = _parse_filter_instant(parsed.after)
            if bound is not None and created < bound:
                return False
        if parsed.on is not None:
            bound = _parse_filter_instant(parsed.on)
            if bound is not None and created.date() != bound.date():
                return False
        return True

    def _apply_as_of(
        self, candidates: list[tuple[str, float]], as_of: str
    ) -> list[tuple[str, float]]:
        """Drop candidates created after the as-of instant.

        As-of retrieval answers "what could be known at time T": items
        whose ``created_at`` is strictly after the bound are excluded,
        items exactly at the bound are kept, and undated items stay
        visible (they carry no evidence of arriving later). The filter
        runs after graph expansion so expanded items are screened too.
        An unparseable ``as_of`` disables the filter.
        """
        bound = _parse_filter_instant(as_of)
        if bound is None:
            return candidates
        kept: list[tuple[str, float]] = []
        for item_id, score in candidates:
            item = self.store.get(item_id)
            if item is not None and item.created_at:
                created = _parse_filter_instant(item.created_at)
                if created is not None and created > bound:
                    continue
            kept.append((item_id, score))
        return kept

    def _expand_with_graph(
        self,
        candidates: list[tuple[str, float]],
        discount: float,
        extra_reasons: dict[str, list[str]],
    ) -> list[tuple[str, float]]:
        """Add items linked through the entity graph to the candidate pool.

        For every base candidate, items attached to a graph neighbor of
        its entities join the pool with score ``base * discount`` (the
        best source wins). Entity and neighbor iteration is sorted, so
        expansion is deterministic for identical inputs.
        """
        present = {item_id for item_id, _ in candidates}
        additions: dict[str, tuple[float, str]] = {}
        for item_id, score in candidates:
            item = self.store.get(item_id)
            if item is None or self.graph is None:
                continue
            for entity_id in sorted(str(e) for e in item.metadata.get("entity_ids", ())):
                neighbors = sorted(self.graph.neighbors(entity_id), key=lambda n: n.node_id)
                for neighbor in neighbors:
                    for related_id in sorted(self._entity_index.get(neighbor.node_id, ())):
                        if related_id in present:
                            continue
                        expanded = score * discount
                        via = f"graph:{entity_id}->{neighbor.node_id}"
                        current = additions.get(related_id)
                        if current is None or expanded > current[0]:
                            additions[related_id] = (expanded, via)
        merged = list(candidates)
        for related_id in sorted(additions):
            expanded, via = additions[related_id]
            merged.append((related_id, expanded))
            extra_reasons.setdefault(related_id, []).append(f"expanded_via={via}")
        return merged

    def _apply_fusion(
        self,
        candidates: list[tuple[str, float]],
        weights: FusionWeights,
        now: str,
        extra_reasons: dict[str, list[str]],
    ) -> list[tuple[str, float]]:
        """Refold candidate scores from relevance, importance, and recency.

        Relevance is normalized by the best candidate score so the three
        components share a comparable [0, 1] scale. Undated items get no
        recency contribution. Component values are recorded as reasons so
        every fused ranking stays explainable.
        """
        if not candidates:
            return candidates
        now_dt = _parse_filter_instant(now) if now else None
        if weights.recency > 0 and now_dt is None:
            raise ValueError("recency fusion requires a valid 'now' timestamp")
        max_score = max(score for _, score in candidates)
        fused: list[tuple[str, float]] = []
        for item_id, score in candidates:
            item = self.store.get(item_id)
            relevance = score / max_score if max_score > 0 else 0.0
            salience = item.salience if item is not None else 0.0
            age_days: float | None = None
            if now_dt is not None and item is not None and item.created_at:
                created = _parse_filter_instant(item.created_at)
                if created is not None:
                    age_days = (now_dt - created).total_seconds() / 86400.0
            recency_component = 0.0
            if age_days is not None:
                recency_component = 0.5 ** (max(0.0, age_days) / weights.half_life_days)
            fused.append((item_id, fuse_score(relevance, salience, age_days, weights)))
            extra_reasons.setdefault(item_id, []).extend(
                [
                    f"relevance={round(relevance, 6)}",
                    f"importance={round(salience, 6)}",
                    f"recency={round(recency_component, 6)}",
                ]
            )
        fused.sort(key=lambda pair: (-pair[1], pair[0]))
        return fused

    def _finalize(
        self,
        candidates: list[tuple[str, float]],
        query_text: str,
        *,
        top_k: int,
        lambda_mmr: float,
        extra_reasons: dict[str, list[str]] | None = None,
    ) -> list[SearchResult]:
        """MMR-rerank candidates and attach citations to surviving items."""
        texts = {}
        for item_id, _ in candidates:
            item = self.store.get(item_id)
            if item:
                texts[item_id] = f"{item.title} {item.content}"

        ranked_ids = mmr_rerank(candidates, texts, lambda_param=lambda_mmr, top_k=top_k)

        results: list[SearchResult] = []
        score_map = dict(candidates)
        for item_id in ranked_ids:
            item = self.store.get(item_id)
            if item is None:
                continue
            snippet = self._make_snippet(item.content, query_text)
            citation = f"[{item.item_id}]"
            reasons = [f"score={score_map.get(item_id, 0.0):.6f}"]
            if extra_reasons:
                reasons.extend(extra_reasons.get(item_id, []))
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
        """Window the text around the earliest query-term match.

        Falls back to a head truncation when no query term occurs in the
        text. The returned window is at most ``max_len`` characters of
        content, plus ``...`` markers on the elided sides.
        """
        if len(text) <= max_len:
            return text
        lowered = text.lower()
        match_at = -1
        for term in tokenize(query):
            found = lowered.find(term)
            if found != -1 and (match_at == -1 or found < match_at):
                match_at = found
        if match_at == -1:
            return text[:max_len] + "..."
        start = max(0, match_at - max_len // 4)
        end = min(len(text), start + max_len)
        start = max(0, end - max_len)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return prefix + text[start:end] + suffix

    def property_citations_resolve(self, query: str) -> bool:
        """Property test: all result citations point to existing items."""
        results = self.search(query)
        return all(self.store.get(r.item_id) is not None for r in results)


def _parse_filter_instant(value: str) -> datetime | None:
    """Parse an ISO date/datetime filter value; naive means UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# --- Query parsing -----------------------------------------------------------

_FILTER_RE = re.compile(
    r"(?:^|\s)(?P<key>tag|person|project|before|after|on):(?P<value>\S+)",
    re.IGNORECASE,
)

_LIST_FILTERS = ("tag", "person", "project")
_INSTANT_FILTERS = ("before", "after", "on")

_NEG_FILTER_RE = re.compile(
    r"(?:^|\s)-(?P<key>tag|person|project):(?P<value>\S+)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ParsedQuery:
    """Structured form of a query string.

    Grammar (all filters optional, in any position):

    * ``tag:<t>``, ``person:<p>``, ``project:<pr>`` — accumulate, matched
      case-insensitively;
    * ``before:<iso>``, ``after:<iso>``, ``on:<iso>`` — temporal bounds,
      last occurrence wins;
    * ``-tag:<t>``, ``-person:<p>``, ``-project:<pr>`` and a bare
      ``-term`` — exclusions: matching items are dropped from results;
    * everything else is free text for BM25.
    """

    text: str = ""
    tags: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    before: str | None = None
    after: str | None = None
    on: str | None = None
    excluded_tags: list[str] = field(default_factory=list)
    excluded_people: list[str] = field(default_factory=list)
    excluded_projects: list[str] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tags": list(self.tags),
            "people": list(self.people),
            "projects": list(self.projects),
            "before": self.before,
            "after": self.after,
            "on": self.on,
            "excluded_tags": list(self.excluded_tags),
            "excluded_people": list(self.excluded_people),
            "excluded_projects": list(self.excluded_projects),
            "excluded_terms": list(self.excluded_terms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParsedQuery:
        return cls(
            text=data.get("text", ""),
            tags=list(data.get("tags", [])),
            people=list(data.get("people", [])),
            projects=list(data.get("projects", [])),
            before=data.get("before"),
            after=data.get("after"),
            on=data.get("on"),
            excluded_tags=list(data.get("excluded_tags", [])),
            excluded_people=list(data.get("excluded_people", [])),
            excluded_projects=list(data.get("excluded_projects", [])),
            excluded_terms=list(data.get("excluded_terms", [])),
        )

    def has_filters(self) -> bool:
        return bool(
            self.tags
            or self.people
            or self.projects
            or self.before
            or self.after
            or self.on
            or self.excluded_tags
            or self.excluded_people
            or self.excluded_projects
            or self.excluded_terms
        )


def parse_query(raw: str) -> ParsedQuery:
    """Split a raw query string into filters, exclusions and free text.

    Positive filters (``tag:x``) and their negations (``-tag:x``) are
    extracted first; a bare ``-word`` excludes items containing that
    token. Negations never cancel positives — ``tag:a -tag:a`` matches
    items tagged ``a`` and then drops them, yielding no results.
    """
    parsed = ParsedQuery()
    for match in _FILTER_RE.finditer(raw):
        key = match.group("key").lower()
        value = match.group("value")
        if key in _LIST_FILTERS:
            target = {"tag": parsed.tags, "person": parsed.people, "project": parsed.projects}[key]
            lowered = value.lower()
            if lowered not in target:
                target.append(lowered)
        elif key in _INSTANT_FILTERS:
            setattr(parsed, key, value)
    neg_targets = {
        "tag": parsed.excluded_tags,
        "person": parsed.excluded_people,
        "project": parsed.excluded_projects,
    }
    for match in _NEG_FILTER_RE.finditer(raw):
        target = neg_targets[match.group("key").lower()]
        lowered = match.group("value").lower()
        if lowered not in target:
            target.append(lowered)
    remainder = _NEG_FILTER_RE.sub(" ", _FILTER_RE.sub(" ", raw))
    kept: list[str] = []
    for token in remainder.split():
        if len(token) > 1 and token.startswith("-"):
            term = token[1:].lower()
            if term and term not in parsed.excluded_terms:
                parsed.excluded_terms.append(term)
        else:
            kept.append(token)
    parsed.text = " ".join(kept)
    return parsed


# --- Score fusion --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FusionWeights:
    """Weights for fusing relevance, importance, and recency.

    ``half_life_days`` controls exponential recency decay, in the spirit
    of Ebbinghaus forgetting-curve modeling: an item loses half of its
    recency contribution per half-life. Weights must be non-negative and
    not all zero.
    """

    relevance: float = 1.0
    importance: float = 0.0
    recency: float = 0.0
    half_life_days: float = 14.0

    def __post_init__(self) -> None:
        if min(self.relevance, self.importance, self.recency) < 0:
            raise ValueError("fusion weights must be non-negative")
        if self.relevance + self.importance + self.recency <= 0:
            raise ValueError("fusion weights must not all be zero")
        if self.half_life_days <= 0:
            raise ValueError("half_life_days must be positive")


def fuse_score(
    relevance: float,
    salience: float,
    age_days: float | None,
    weights: FusionWeights,
) -> float:
    """Weighted sum of normalized relevance, importance, and recency.

    ``relevance`` is expected in [0, 1] (caller normalizes), ``salience``
    is the item's importance in [0, 1], and ``age_days`` is the item age
    (``None`` for undated items contributes no recency). The result is
    quantized here, at the production point, so digests stay stable.
    """
    recency = 0.0
    if age_days is not None:
        recency = 0.5 ** (max(0.0, age_days) / weights.half_life_days)
    fused = (
        weights.relevance * relevance + weights.importance * salience + weights.recency * recency
    )
    return round(fused, 6)


# --- Right-to-forget wiring -----------------------------------------------------


def build_deletion_engine(
    engine: RetrievalEngine,
    is_protected: Callable[[str], bool] | None = None,
) -> DeletionEngine:
    """Wire a DeletionEngine to a retrieval engine's store and index.

    Cascade follows each item's ``metadata["cascade"]`` list of related
    ids (e.g. memories derived from the deleted one). Deleting removes
    the item from the memory store and the BM25 index, then tombstones
    the id so it cannot be re-derived or re-indexed later. Lookups go
    through ``peek`` so deletion never inflates access statistics.
    """
    store = engine.store

    def get_target(key: str) -> GraphDeletionTarget | None:
        item = store.peek(key)
        if item is None:
            return None
        outgoing = [str(related) for related in item.metadata.get("cascade", [])]
        return GraphDeletionTarget(key=key, kind="memory", outgoing_relations=outgoing)

    def delete_item(key: str, kind: str, reason: DeletionReason, now: datetime) -> bool:
        store.remove(key)
        engine.index.remove(key)
        for holders in engine._entity_index.values():
            holders.discard(key)
        return store.peek(key) is None

    return DeletionEngine(
        get_target=get_target,
        delete_item=delete_item,
        is_protected=is_protected or (lambda _key: False),
    )


def forget(
    deletion: DeletionEngine,
    item_id: str,
    reason: DeletionReason,
    now: datetime,
    requested_by: str | None = None,
) -> DeletionReport:
    """Delete an item with cascade and return the audit report."""
    return deletion.delete(item_id, reason, now, requested_by=requested_by)


def safe_index(engine: RetrievalEngine, deletion: DeletionEngine, item: MemoryItem) -> bool:
    """Index an item unless its id is tombstoned (blocks re-derivation).

    Returns True when the item was stored and indexed, False when a
    tombstone refused it — deleted content must never reappear through
    re-ingestion of surviving sources.
    """
    if deletion.is_deleted(item.item_id):
        return False
    engine.store.add(item)
    engine.index_item(item)
    return True
