"""Meeting preparation: gather evidence and assemble cited packets.

Collects related people, projects, open commitments, and unresolved
decisions from memory; assembles an agenda from evidence; produces a
cited Markdown/HTML packet; measures coverage against planted prep facts.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier


@dataclass(slots=True)
class PrepItem:
    """A piece of evidence in a meeting prep packet."""

    item_id: str
    title: str
    category: str  # person, project, commitment, decision, note
    summary: str
    citation: str
    priority: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Deterministic dict form; priority quantized to 6 decimals."""
        return {
            "item_id": self.item_id,
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "citation": self.citation,
            "priority": round(self.priority, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrepItem:
        """Rebuild an item from :meth:`to_dict` output."""
        return cls(
            item_id=data["item_id"],
            title=data.get("title", ""),
            category=data.get("category", ""),
            summary=data.get("summary", ""),
            citation=data.get("citation", ""),
            priority=float(data.get("priority", 0.0)),
        )


@dataclass(slots=True)
class MeetingPrep:
    """A prepared meeting packet."""

    meeting_id: str
    meeting_title: str
    attendee_names: list[str] = field(default_factory=list)
    agenda_items: list[str] = field(default_factory=list)
    items: list[PrepItem] = field(default_factory=list)
    total_items: int = 0
    cited_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic dict form of the whole packet."""
        return {
            "meeting_id": self.meeting_id,
            "meeting_title": self.meeting_title,
            "attendee_names": list(self.attendee_names),
            "agenda_items": list(self.agenda_items),
            "items": [item.to_dict() for item in self.items],
            "total_items": self.total_items,
            "cited_sources": list(self.cited_sources),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetingPrep:
        """Rebuild a packet from :meth:`to_dict` output."""
        return cls(
            meeting_id=data["meeting_id"],
            meeting_title=data.get("meeting_title", ""),
            attendee_names=list(data.get("attendee_names", [])),
            agenda_items=list(data.get("agenda_items", [])),
            items=[PrepItem.from_dict(item) for item in data.get("items", [])],
            total_items=int(data.get("total_items", 0)),
            cited_sources=list(data.get("cited_sources", [])),
        )

    def to_markdown(self) -> str:
        lines = [f"# Meeting Prep: {self.meeting_title}", ""]
        lines.append(f"**Meeting ID**: `{self.meeting_id}`")
        lines.append(f"**Attendees**: {', '.join(self.attendee_names)}")
        lines.append("")
        lines.append("## Agenda")
        lines.append("")
        for i, item in enumerate(self.agenda_items, 1):
            lines.append(f"{i}. {item}")
        lines.append("")
        lines.append(f"## Background ({self.total_items} items)")
        lines.append("")
        by_cat: dict[str, list[PrepItem]] = {}
        for entry in self.items:
            by_cat.setdefault(entry.category, []).append(entry)
        for cat in sorted(by_cat.keys()):
            lines.append(f"### {cat.title()} ({len(by_cat[cat])})")
            lines.append("")
            for pitem in by_cat[cat]:
                lines.append(f"**{pitem.title}** {pitem.citation}")
                lines.append(f"> {pitem.summary}")
                lines.append("")
        lines.append("---")
        lines.append(f"*Sources cited: {len(self.cited_sources)}*")
        return "\n".join(lines)

    def to_html(self) -> str:
        parts = [
            "<!DOCTYPE html>",
            '<html lang="en"><head><meta charset="utf-8">',
            f"<title>Meeting Prep: {html.escape(self.meeting_title)}</title>",
            "<style>",
            "body{font-family:system-ui,sans-serif;max-width:800px;margin:2em auto;padding:0 1em;}",
            ".citation{color:#666;font-size:0.8em;}",
            ".item{border-left:3px solid #ddd;padding-left:1em;margin:1em 0;}",
            "h1{border-bottom:2px solid #333;}",
            "h3{margin-top:1.5em;}",
            "</style></head><body>",
            f"<h1>Meeting Prep: {html.escape(self.meeting_title)}</h1>",
            f"<p><strong>Meeting ID:</strong> <code>{html.escape(self.meeting_id)}</code></p>",
            f"<p><strong>Attendees:</strong> {html.escape(', '.join(self.attendee_names))}</p>",
            "<h2>Agenda</h2><ol>",
        ]
        for item in self.agenda_items:
            parts.append(f"<li>{html.escape(item)}</li>")
        parts.append("</ol>")
        parts.append(f"<h2>Background ({self.total_items} items)</h2>")
        by_cat: dict[str, list[PrepItem]] = {}
        for entry in self.items:
            by_cat.setdefault(entry.category, []).append(entry)
        for cat in sorted(by_cat.keys()):
            parts.append(f"<h3>{html.escape(cat.title())} ({len(by_cat[cat])})</h3>")
            for pitem in by_cat[cat]:
                parts.append('<div class="item">')
                parts.append(
                    f"<strong>{html.escape(pitem.title)}</strong> "
                    f'<span class="citation">{html.escape(pitem.citation)}</span>'
                )
                parts.append(f"<blockquote>{html.escape(pitem.summary)}</blockquote>")
                parts.append("</div>")
        parts.append("<hr>")
        parts.append(f"<p><em>Sources cited: {len(self.cited_sources)}</em></p>")
        parts.append("</body></html>")
        return "\n".join(parts)


@dataclass
class MeetingPrepper:
    """Assembles meeting prep packets from memory."""

    store: MemoryStore
    max_items: int = 20

    def prepare(
        self,
        meeting_id: str,
        meeting_title: str,
        attendees: list[str],
        context_text: str = "",
    ) -> MeetingPrep:
        """Prepare a meeting packet for the given meeting."""
        prep = MeetingPrep(
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            attendee_names=list(attendees),
        )

        # Gather relevant items
        candidate_items: list[MemoryItem] = []
        candidate_items.extend(self.store.items_by_tier(MemoryTier.SEMANTIC))
        candidate_items.extend(self.store.items_by_tier(MemoryTier.EPISODIC))

        # Score items by relevance (simple keyword match against attendees + title)
        keywords = {a.lower() for a in attendees} | set(meeting_title.lower().split())
        if context_text:
            keywords |= set(context_text.lower().split())

        scored: list[tuple[MemoryItem, float]] = []
        for item in candidate_items:
            score = self._relevance_score(item, keywords)
            if score > 0:
                scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[: self.max_items]

        # Build prep items
        for item, score in scored:
            cat = self._categorize(item)
            summary = item.content[:200] + "..." if len(item.content) > 200 else item.content
            prep_item = PrepItem(
                item_id=item.item_id,
                title=item.title or item.item_id,
                category=cat,
                summary=summary,
                citation=f"[{item.item_id}]",
                priority=score,
            )
            prep.items.append(prep_item)
            prep.cited_sources.append(item.item_id)

        prep.total_items = len(prep.items)
        prep.agenda_items = self._build_agenda(prep.items)

        return prep

    def _build_agenda(self, items: list[PrepItem]) -> list[str]:
        """Evidence-based agenda assembled from the packet's own items.

        Commitments come first, then decisions, then one focus entry per
        remaining category (highest-priority item, id as tie-break), and
        the standard discussion/action slots close the agenda. Every
        evidence-derived line cites the memory ids it was built from, so
        the agenda never contains claims the packet cannot source.
        """
        agenda: list[str] = []
        by_cat: dict[str, list[PrepItem]] = {}
        for entry in items:
            by_cat.setdefault(entry.category, []).append(entry)
        commitments = by_cat.get("commitment", [])
        if commitments:
            cites = ", ".join(c.item_id for c in commitments[:3])
            agenda.append(f"Review open commitments ({len(commitments)}) - cites {cites}")
        decisions = by_cat.get("decision", [])
        if decisions:
            cites = ", ".join(d.item_id for d in decisions[:3])
            agenda.append(f"Confirm pending decisions ({len(decisions)}) - cites {cites}")
        for cat in sorted(by_cat):
            if cat in ("commitment", "decision"):
                continue
            top = max(by_cat[cat], key=lambda e: (e.priority, e.item_id))
            agenda.append(f"{cat.title()} focus: {top.title} - cites {top.item_id}")
        agenda.extend(["Open discussion", "Action items"])
        return agenda

    def _relevance_score(self, item: MemoryItem, keywords: set[str]) -> float:
        text = f"{item.title} {item.content}".lower()
        words = set(text.split())
        if not keywords:
            return 0.0
        matches = len(keywords & words)
        return matches / len(keywords)

    def _categorize(self, item: MemoryItem) -> str:
        tags = {t.lower() for t in item.tags}
        if "commitment" in tags or "commitments" in tags:
            return "commitment"
        if "decision" in tags or "decisions" in tags:
            return "decision"
        if "person" in tags or "people" in tags:
            return "person"
        if "project" in tags:
            return "project"
        if "note" in tags:
            return "note"
        return "background"


def verify_citations(prep: MeetingPrep, store: MemoryStore) -> bool:
    """Property: all cited sources exist in the store."""
    return all(store.get(cid) is not None for cid in prep.cited_sources)


@dataclass(slots=True)
class CoverageReport:
    """How completely a packet covers a set of expected (planted) facts."""

    expected: int
    covered: int
    missing: list[str] = field(default_factory=list)
    per_category: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        return round(self.covered / self.expected, 6) if self.expected else 1.0

    @property
    def category_coverage(self) -> float:
        """Fraction of expected categories with at least one hit."""
        if not self.per_category:
            return 1.0
        cats_with_hit = sum(1 for _, covered in self.per_category.values() if covered > 0)
        return round(cats_with_hit / len(self.per_category), 6)

    def recall_by_category(self, category: str) -> float:
        """Recall for a specific expected category, or 1.0 if none expected."""
        if category not in self.per_category:
            return 1.0
        expected, covered = self.per_category[category]
        if expected == 0:
            return 1.0
        return round(covered / expected, 6)


def measure_coverage(
    prep: MeetingPrep,
    expected_ids: list[str],
    expected_categories: dict[str, str] | None = None,
) -> CoverageReport:
    """Measure how many expected source ids a packet actually cites.

    ``expected_ids`` is the planted ground truth for a synthetic meeting:
    the memory ids a correct packet should surface. Coverage is the count
    of expected ids present in the packet's cited sources; missing ids are
    reported so shortfalls are visible, never averaged away. An empty
    expectation yields ratio 1.0 (nothing required, nothing missed).

    When ``expected_categories`` is provided as ``{item_id: category}``,
    the report also tracks per-category hit counts and the fraction of
    categories with at least one covered item.
    """
    cited = set(prep.cited_sources)
    unique_expected = sorted(set(expected_ids))
    missing = [eid for eid in unique_expected if eid not in cited]
    per_category: dict[str, tuple[int, int]] = {}
    if expected_categories:
        cat_expected: dict[str, int] = {}
        cat_covered: dict[str, int] = {}
        for eid in unique_expected:
            cat = expected_categories.get(eid, "other")
            cat_expected[cat] = cat_expected.get(cat, 0) + 1
            if eid in cited:
                cat_covered[cat] = cat_covered.get(cat, 0) + 1
        for cat in sorted(cat_expected):
            per_category[cat] = (cat_expected[cat], cat_covered.get(cat, 0))
    return CoverageReport(
        expected=len(unique_expected),
        covered=len(unique_expected) - len(missing),
        missing=missing,
        per_category=per_category,
    )
