"""Standup and weekly review reports.

Deterministic reports with Markdown/HTML/SVG output, commitment timeline,
workload heat strip, and citation of memory IDs.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from mnemofold.ledger import CommitmentLedger, CommitmentStatus
from mnemofold.reports import wrap_html


def _parse_instant(value: str) -> datetime | None:
    """Parse an ISO instant; naive values are read as UTC. None if invalid."""
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _day_window(today: str) -> tuple[datetime, datetime]:
    """[midnight, next midnight) around the given instant, in its own zone."""
    moment = _parse_instant(today)
    if moment is None:
        raise ValueError(f"invalid standup date: {today!r}")
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


@dataclass(slots=True)
class StandupData:
    date: str
    completed: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    open_commitments: list[str] = field(default_factory=list)
    overdue: list[str] = field(default_factory=list)
    pending_decisions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


@dataclass
class StandupGenerator:
    ledger: CommitmentLedger

    def generate(self, today: str, pending_decisions: list[str] | None = None) -> StandupData:
        """Build the standup snapshot for ``today``.

        ``completed`` lists commitments transitioned to done on the same
        local day as ``today`` (read from the ledger's history); callers
        that track decisions elsewhere can pass ``pending_decisions`` to
        have them carried into the report.
        """
        data = StandupData(date=today)
        data.pending_decisions = list(pending_decisions or [])
        day_start, day_end = _day_window(today)
        for c in self.ledger.all_commitments():
            if c.status != CommitmentStatus.DONE:
                continue
            done_at = _parse_instant(c.updated_at)
            if done_at is not None and day_start <= done_at < day_end:
                data.completed.append(f"{c.description} [{c.commitment_id}]")
                data.citations.append(c.commitment_id)
        overdue = self.ledger.overdue(today)
        data.overdue = [
            f"{c.description} [{c.commitment_id}]"
            for c in sorted(overdue, key=lambda x: x.due_date)
        ]
        for c in overdue:
            data.citations.append(c.commitment_id)
        open_c = self.ledger.by_status(CommitmentStatus.OPEN)
        data.open_commitments = [
            f"{c.description} [{c.commitment_id}]"
            for c in sorted(open_c, key=lambda x: x.due_date)[:5]
        ]
        for c in open_c[:5]:
            data.citations.append(c.commitment_id)
        in_prog = self.ledger.by_status(CommitmentStatus.IN_PROGRESS)
        data.in_progress = [f"{c.description} [{c.commitment_id}]" for c in in_prog]
        for c in in_prog:
            data.citations.append(c.commitment_id)
        upcoming = self.ledger.upcoming(today, days=1)
        data.planned = [f"{c.description} ({c.due_date}) [{c.commitment_id}]" for c in upcoming[:5]]
        for c in upcoming[:5]:
            data.citations.append(c.commitment_id)
        data.blockers = list(data.overdue[:3])
        return data


def render_standup_markdown(data: StandupData) -> str:
    lines = [f"# Standup — {data.date}", ""]
    for title, items in [
        ("Completed", data.completed),
        ("In progress", data.in_progress),
        ("Planned", data.planned),
        ("Blockers", data.blockers),
        ("Open commitments", data.open_commitments),
        ("Overdue", data.overdue),
    ]:
        lines.append(f"## {title}")
        lines.append("")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("_None_")
        lines.append("")
    lines.append("---")
    lines.append(f"*Citations: {len(data.citations)}*")
    return "\n".join(lines)


def render_standup_html(data: StandupData) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>Standup - {html.escape(data.date)}</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:700px;margin:2em auto;padding:0 1em;}",
        "h1{border-bottom:2px solid #333;}.overdue{color:#c33;font-weight:bold;}",
        "</style></head><body>",
        f"<h1>Standup — {html.escape(data.date)}</h1>",
    ]
    for title, items, cls in [
        ("Completed", data.completed, ""),
        ("In progress", data.in_progress, ""),
        ("Planned", data.planned, ""),
        ("Blockers", data.blockers, "overdue"),
        ("Open commitments", data.open_commitments, ""),
        ("Overdue", data.overdue, "overdue"),
    ]:
        parts.append(f"<h2>{html.escape(title)}</h2>")
        if items:
            parts.append("<ul>")
            for item in items:
                c = " style='color:#c33;font-weight:bold;'" if cls else ""
                parts.append(f"<li{c}>{html.escape(item)}</li>")
            parts.append("</ul>")
        else:
            parts.append("<p><em>None</em></p>")
    parts.append("<hr>")
    parts.append(f"<p><em>Citations: {len(data.citations)}</em></p>")
    parts.append("</body></html>")
    return "\n".join(parts)


@dataclass(slots=True)
class WeeklyReview:
    """A one-week roll-up of ledger activity, with citations."""

    week_start: str
    week_end: str
    completed: list[str] = field(default_factory=list)
    overdue: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    due_next_week: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class WeeklyReviewGenerator:
    """Builds a weekly review from the ledger's transition history.

    ``completed`` is derived from status-change history entries whose
    timestamp lands inside ``[week_start, week_end)``, so the report
    reflects what actually changed during the week rather than the
    end-state alone. Overdue and open lists are evaluated as of
    ``week_end``. Every line cites its commitment id.
    """

    ledger: CommitmentLedger

    def generate(self, week_start: str, week_end: str) -> WeeklyReview:
        review = WeeklyReview(week_start=week_start, week_end=week_end)
        start = _parse_instant(week_start)
        end = _parse_instant(week_end)

        if start is not None and end is not None:
            for entry in self.ledger.transition_history():
                if entry.get("to_status") != str(CommitmentStatus.DONE):
                    continue
                moment = _parse_instant(str(entry.get("timestamp", "")))
                if moment is not None and start <= moment < end:
                    cid = entry.get("commitment_id", "")
                    commitment = self.ledger.get(cid)
                    label = commitment.description if commitment else cid
                    review.completed.append(f"{label} [{cid}]")
                    review.citations.append(cid)

        overdue = sorted(self.ledger.overdue(week_end), key=lambda c: c.due_date)
        review.overdue = [
            f"{c.description} (due {c.due_date}) [{c.commitment_id}]" for c in overdue
        ]
        review.citations.extend(c.commitment_id for c in overdue)

        active = sorted(
            self.ledger.by_status(CommitmentStatus.OPEN)
            + self.ledger.by_status(CommitmentStatus.IN_PROGRESS),
            key=lambda c: (c.due_date, c.commitment_id),
        )
        review.still_open = [f"{c.description} [{c.commitment_id}]" for c in active]
        review.citations.extend(c.commitment_id for c in active)

        upcoming = [
            c for c in self.ledger.upcoming(week_end, days=7.0) if not c.is_overdue(week_end)
        ]
        review.due_next_week = [
            f"{c.description} (due {c.due_date}) [{c.commitment_id}]" for c in upcoming
        ]
        review.citations.extend(c.commitment_id for c in upcoming)

        # Risks: overdue items are surfaced again as the week's top risk,
        # plus any open commitment already within a day of its deadline.
        review.risks = list(review.overdue)
        soon = _parse_instant(week_end)
        if soon is not None:
            for c in active:
                due = _parse_instant(c.due_date)
                if due is not None and timedelta(0) <= (due - soon) <= timedelta(days=1):
                    line = f"{c.description} is due within a day [{c.commitment_id}]"
                    if line not in review.risks:
                        review.risks.append(line)

        review.stats = {
            "completed_count": len(review.completed),
            "overdue_count": len(review.overdue),
            "still_open_count": len(review.still_open),
            "due_next_week_count": len(review.due_next_week),
            "risk_count": len(review.risks),
            "citation_count": len(set(review.citations)),
        }
        return review


def render_work_strip_svg(counts: list[int], width: int = 600, height: int = 40) -> str:
    if not counts:
        return f'<svg width="{width}" height="{height}"></svg>'
    max_val = max(counts) or 1
    bar_w = width / len(counts)
    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    for i, count in enumerate(counts):
        intensity = count / max_val
        r = int(200 * (1 - intensity) + 55)
        g = int(200 * (1 - intensity) + 55)
        b = int(240 * (1 - intensity) + 15)
        x = int(i * bar_w)
        w = int(bar_w) + 1
        parts.append(f'<rect x="{x}" y="0" width="{w}" height="{height}" fill="rgb({r},{g},{b})"/>')
    parts.append("</svg>")
    return "".join(parts)


# --- Weekly review rendering ----------------------------------------------------

_WEEKLY_SECTIONS = (
    ("Completed", "completed"),
    ("Overdue", "overdue"),
    ("Still open", "still_open"),
    ("Due next week", "due_next_week"),
    ("Risks", "risks"),
)


def render_weekly_markdown(review: WeeklyReview) -> str:
    """Deterministic Markdown for a weekly review."""
    lines = [f"# Weekly Review — {review.week_start} → {review.week_end}", ""]
    if review.stats:
        lines.append("## Summary")
        lines.append("")
        stats_items = [
            ("Completed", review.stats.get("completed_count", 0)),
            ("Overdue", review.stats.get("overdue_count", 0)),
            ("Still open", review.stats.get("still_open_count", 0)),
            ("Due next week", review.stats.get("due_next_week_count", 0)),
            ("Risks", review.stats.get("risk_count", 0)),
        ]
        for label, value in stats_items:
            lines.append(f"- **{label}**: {value}")
        lines.append("")
    for title, attribute in _WEEKLY_SECTIONS:
        items: list[str] = getattr(review, attribute)
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("_None_")
        lines.append("")
    lines.append("---")
    lines.append(f"*Citations: {len(review.citations)}*")
    return "\n".join(lines)


def render_weekly_html(review: WeeklyReview) -> str:
    """Self-contained HTML page for a weekly review; all text escaped."""
    sections: list[tuple[str, str]] = []
    for title, attribute in _WEEKLY_SECTIONS:
        items: list[str] = getattr(review, attribute)
        if items:
            body = "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"
        else:
            body = "<p><em>None</em></p>"
        sections.append((f"{title} ({len(items)})", body))
    sections.append(("Citations", f"<p><em>{len(review.citations)} memory ids cited</em></p>"))
    return wrap_html(f"Weekly Review {review.week_start} → {review.week_end}", sections)


def compare_reviews(previous: WeeklyReview, current: WeeklyReview) -> dict[str, Any]:
    """Week-over-week delta between two weekly reviews.

    Every list difference is sorted and expressed with the commitment
    ids (and risk strings) the two reviews already cite — the delta
    never introduces claims of its own. ``stats_delta`` subtracts the
    previous integer stats from the current ones key by key, covering
    the union of both weeks' stat keys.
    """
    return {
        "previous_week": [previous.week_start, previous.week_end],
        "current_week": [current.week_start, current.week_end],
        "completed_new": sorted(set(current.completed) - set(previous.completed)),
        "completed_no_longer_listed": sorted(set(previous.completed) - set(current.completed)),
        "overdue_new": sorted(set(current.overdue) - set(previous.overdue)),
        "overdue_cleared": sorted(set(previous.overdue) - set(current.overdue)),
        "still_open_new": sorted(set(current.still_open) - set(previous.still_open)),
        "still_open_cleared": sorted(set(previous.still_open) - set(current.still_open)),
        "risks_added": sorted(set(current.risks) - set(previous.risks)),
        "risks_removed": sorted(set(previous.risks) - set(current.risks)),
        "stats_delta": {
            key: current.stats.get(key, 0) - previous.stats.get(key, 0)
            for key in sorted(set(current.stats) | set(previous.stats))
        },
    }
