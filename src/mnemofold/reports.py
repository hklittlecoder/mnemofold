"""Report rendering utilities.

Deterministic Markdown plus self-contained HTML with embedded SVG
(commitment timeline, folding summary, workload heat strip).  All
text is HTML-escaped; no external dependencies.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date


def escape_text(text: str) -> str:
    """HTML-escape text for safe embedding in reports."""
    return html.escape(text, quote=True)


def render_markdown_heading(text: str, level: int = 1) -> str:
    """Render a Markdown heading."""
    return "#" * level + " " + text


def render_markdown_list(items: list[str]) -> str:
    """Render a Markdown bulleted list."""
    return "\n".join(f"- {item}" for item in items)


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a Markdown table."""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _svg_rect(x: int, y: int, w: int, h: int, fill: str = "#333") -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" />'


def _svg_text(x: int, y: int, text: str, size: int = 12, fill: str = "#333") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'font-family="monospace">{escape_text(text)}</text>'
    )


def render_workload_strip(
    day_counts: list[int],
    width: int = 600,
    bar_height: int = 20,
) -> str:
    """Render an SVG workload heat strip (one bar per day).

    ``day_counts`` is a list of event counts per day.  Bar width scales
    so that the total fits in ``width``.
    """
    if not day_counts:
        return ""
    n = len(day_counts)
    max_count = max(day_counts) or 1
    bar_w = max(1, width // n)
    total_w = bar_w * n
    height = bar_height + 20

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{height}" viewBox="0 0 {total_w} {height}">'
    ]

    for i, count in enumerate(day_counts):
        h = int(bar_height * count / max_count)
        y = bar_height - h
        # Green gradient intensity based on count
        intensity = min(200, 55 + int(200 * count / max_count))
        fill = f"rgb({255 - intensity}, {intensity}, 100)"
        parts.append(_svg_rect(i * bar_w, y, bar_w - 1, h, fill=fill))

    parts.append(_svg_text(0, bar_height + 15, f"{n} days, max={max_count}", size=10))
    parts.append("</svg>")
    return "\n".join(parts)


@dataclass
class TimelineItem:
    label: str
    start: date
    end: date
    status: str = "open"  # open, done, overdue, cancelled


def render_timeline_svg(
    items: list[TimelineItem],
    width: int = 600,
    row_height: int = 24,
) -> str:
    """Render an SVG timeline (Gantt-style) of commitment items.

    Color-coded by status.  All text is HTML-escaped.
    """
    if not items:
        return ""

    min_date = min(it.start for it in items)
    max_date = max(it.end for it in items)
    total_days = (max_date - min_date).days + 1
    if total_days < 1:
        total_days = 1

    status_colors = {
        "open": "#4a90d9",
        "done": "#4caf50",
        "overdue": "#e53935",
        "cancelled": "#9e9e9e",
    }

    label_width = 180
    chart_width = width - label_width
    height = row_height * len(items) + 30

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    ]

    for i, item in enumerate(items):
        y = i * row_height + 5
        color = status_colors.get(item.status, "#999")

        # Label
        parts.append(_svg_text(5, y + 14, item.label[:28], size=11, fill="#222"))

        # Bar
        start_offset = (item.start - min_date).days
        end_offset = (item.end - min_date).days + 1
        x = label_width + int(chart_width * start_offset / total_days)
        w = max(2, int(chart_width * (end_offset - start_offset) / total_days))
        parts.append(_svg_rect(x, y, w, 16, fill=color))

    # Axis labels
    parts.append(_svg_text(label_width, height - 8, min_date.isoformat(), size=9, fill="#666"))
    parts.append(_svg_text(width - 80, height - 8, max_date.isoformat(), size=9, fill="#666"))
    parts.append("</svg>")
    return "\n".join(parts)


@dataclass
class FoldSummaryItem:
    category: str
    count: int
    merged: int = 0


def render_fold_summary_svg(
    items: list[FoldSummaryItem],
    width: int = 400,
) -> str:
    """Render a bar-chart SVG of fold results by category."""
    if not items:
        return ""
    bar_height = 18
    gap = 4
    label_width = 120
    chart_width = width - label_width - 40
    height = len(items) * (bar_height + gap) + 30
    max_val = max(it.count for it in items) or 1

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    ]

    for i, item in enumerate(items):
        y = i * (bar_height + gap) + 5
        # Label
        parts.append(_svg_text(5, y + 13, item.category[:16], size=11, fill="#222"))
        # Total bar
        total_w = int(chart_width * item.count / max_val)
        parts.append(_svg_rect(label_width, y, total_w, bar_height, fill="#b3d9ff"))
        # Merged bar overlay
        merged_w = int(chart_width * item.merged / max_val)
        if merged_w > 0:
            parts.append(_svg_rect(label_width, y, merged_w, bar_height, fill="#4a90d9"))
        # Count label
        parts.append(
            _svg_text(label_width + total_w + 4, y + 13, str(item.count), size=10, fill="#444")
        )

    parts.append("</svg>")
    return "\n".join(parts)


def wrap_html(
    title: str,
    body_sections: list[tuple[str, str]],
) -> str:
    """Wrap report sections in a complete HTML page.

    ``body_sections`` is a list of (heading, html_content) tuples.
    """
    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           margin: 2em; color: #222; max-width: 900px; }
    h1 { color: #1a365d; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.3em; }
    h2 { color: #2c5282; margin-top: 1.5em; }
    .section { margin: 1em 0; }
    svg { max-width: 100%; height: auto; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #e2e8f0; padding: 0.5em; text-align: left; }
    th { background: #f7fafc; }
    """
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        f"<title>{escape_text(title)}</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        f"<h1>{escape_text(title)}</h1>",
    ]
    for heading, content in body_sections:
        parts.append('<div class="section">')
        parts.append(f"<h2>{escape_text(heading)}</h2>")
        parts.append(content)
        parts.append("</div>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def render_metric_table(metrics: list[tuple[str, float, str]]) -> str:
    """Render a metrics table as HTML.

    ``metrics`` is a list of (name, value, status) tuples.
    """
    rows_html = ""
    for name, value, status in metrics:
        status_class = f"status-{status}"
        rows_html += (
            f"<tr>"
            f"<td>{escape_text(name)}</td>"
            f"<td>{value:.4f}</td>"
            f'<td class="{status_class}">{escape_text(status)}</td>'
            f"</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>Metric</th><th>Value</th><th>Status</th></tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
    )
