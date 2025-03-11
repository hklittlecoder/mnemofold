"""Standup and weekly review reports.

Deterministic reports with Markdown/HTML/SVG output, commitment timeline,
workload heat strip, and citation of memory IDs.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from mnemofold.ledger import CommitmentLedger, CommitmentStatus


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

    def generate(self, today: str) -> StandupData:
        data = StandupData(date=today)
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
