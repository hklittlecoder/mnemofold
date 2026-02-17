"""Report rendering utilities.

Deterministic Markdown plus self-contained HTML with embedded SVG
(commitment timeline, folding summary, workload heat strip).  All
text is HTML-escaped; no external dependencies.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from typing import Any


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
    legend: bool = False,
) -> str:
    """Render an SVG timeline (Gantt-style) of commitment items.

    Color-coded by status.  All text is HTML-escaped.  With
    ``legend=True`` a row of status chips (only for statuses actually
    present) is drawn above the axis labels; the default keeps the
    legacy output byte-identical.
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
    height = row_height * len(items) + 30 + (22 if legend else 0)

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

    if legend:
        used = [s for s in status_colors if any(it.status == s for it in items)]
        x = label_width
        for status_name in used:
            parts.append(_svg_rect(x, height - 28, 10, 10, fill=status_colors[status_name]))
            parts.append(_svg_text(x + 14, height - 19, status_name, size=9, fill="#444"))
            x += 26 + 7 * len(status_name) + 10
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


def assemble_report_page(
    title: str,
    *,
    timeline_items: list[TimelineItem] | None = None,
    fold_items: list[FoldSummaryItem] | None = None,
    day_counts: list[int] | None = None,
    metrics: list[tuple[str, float, str]] | None = None,
    run_metadata: dict[str, str] | None = None,
) -> str:
    """Assemble one self-contained HTML page from the report components.

    Sections with no data are omitted entirely. ``run_metadata`` (seed,
    version, window, ...) renders as a sorted footer table so every
    published report carries its reproduction context. The page embeds
    only inline SVG and CSS — no scripts, no external assets.
    """
    sections: list[tuple[str, str]] = []
    if timeline_items:
        sections.append(("Commitment timeline", render_timeline_svg(timeline_items, legend=True)))
    if fold_items:
        sections.append(("Folding summary", render_fold_summary_svg(fold_items)))
    if day_counts:
        sections.append(("Workload", render_workload_strip(day_counts)))
    if metrics:
        sections.append(("Metrics", render_metric_table(metrics)))
    page = wrap_html(title, sections)
    if run_metadata:
        meta_rows = "".join(
            f"<tr><td>{escape_text(key)}</td><td>{escape_text(str(value))}</td></tr>"
            for key, value in sorted(run_metadata.items())
        )
        footer = (
            '<footer class="run-metadata"><h2>Run metadata</h2>'
            f"<table><tbody>{meta_rows}</tbody></table></footer>"
        )
        page = page.replace("</body>", f"{footer}\n</body>")
    return page


def render_calibration_svg(
    points: list[tuple[float, float]],
    *,
    size: int = 320,
    pad: int = 40,
) -> str:
    """Reliability diagram: predicted probability vs observed rate.

    ``points`` are ``(mean_predicted, observed_rate)`` pairs, e.g.
    derived from ``evaluation.calibration_report`` bins. The dashed
    diagonal is the perfectly-calibrated reference; points above it
    mean the scorer under-predicted. Coordinates are clamped to [0, 1]
    and rounded to 2 decimals, so identical input always renders
    byte-identical SVG.
    """
    span = size - 2 * pad

    def x(predicted: float) -> float:
        return round(pad + min(1.0, max(0.0, predicted)) * span, 2)

    def y(rate: float) -> float:
        return round(pad + (1.0 - min(1.0, max(0.0, rate))) * span, 2)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" role="img" aria-label="calibration reliability diagram">',
        f'<rect x="{pad}" y="{pad}" width="{span}" height="{span}" '
        'fill="#f7fafc" stroke="#e2e8f0"/>',
        f'<line x1="{x(0.0)}" y1="{y(0.0)}" x2="{x(1.0)}" y2="{y(1.0)}" '
        'stroke="#a0aec0" stroke-dasharray="4 3"/>',
    ]
    if points:
        coords = " ".join(f"{x(p)},{y(r)}" for p, r in points)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="#2b6cb0" stroke-width="2"/>')
        for p, r in points:
            parts.append(f'<circle cx="{x(p)}" cy="{y(r)}" r="3" fill="#2b6cb0"/>')
    parts.append(
        f'<text x="{pad}" y="{size - pad // 2}" font-size="10" fill="#4a5568">predicted</text>'
    )
    parts.append(
        f'<text x="{pad // 2}" y="{pad}" font-size="10" fill="#4a5568" '
        f'transform="rotate(-90 {pad // 2} {pad})">observed</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render_burndown_svg(
    series: list[dict[str, Any]],
    *,
    width: int = 640,
    height: int = 200,
    pad: int = 40,
) -> str:
    """Two-line burndown chart: cumulative created vs resolved per day.

    ``series`` entries need ``day``, ``created`` and ``resolved`` keys,
    exactly what ``CommitmentLedger.burndown_series`` produces. The y
    scale is the largest ``created`` value (at least 1); coordinates are
    rounded to 2 decimals so an identical series always renders
    byte-identical SVG. An empty series renders the frame only.
    """
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    scale = max(1, max((int(p.get("created", 0)) for p in series), default=0))
    n = len(series)

    def x(i: int) -> float:
        if n <= 1:
            return float(pad)
        return round(pad + i * inner_w / (n - 1), 2)

    def y(value: int) -> float:
        return round(pad + inner_h - (value / scale) * inner_h, 2)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="commitment burndown">',
        f'<rect x="{pad}" y="{pad}" width="{inner_w}" height="{inner_h}" '
        'fill="#f7fafc" stroke="#e2e8f0"/>',
    ]
    if series:
        created_pts = " ".join(
            f"{x(i)},{y(int(p.get('created', 0)))}" for i, p in enumerate(series)
        )
        resolved_pts = " ".join(
            f"{x(i)},{y(int(p.get('resolved', 0)))}" for i, p in enumerate(series)
        )
        parts.append(
            f'<polyline points="{created_pts}" fill="none" stroke="#2b6cb0" stroke-width="2"/>'
        )
        parts.append(
            f'<polyline points="{resolved_pts}" fill="none" stroke="#2f855a" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{pad}" y="{height - pad // 2}" font-size="10" fill="#4a5568">'
            f"{html.escape(str(series[0].get('day', '')))}</text>"
        )
        parts.append(
            f'<text x="{width - pad}" y="{height - pad // 2}" font-size="10" '
            f'text-anchor="end" fill="#4a5568">'
            f"{html.escape(str(series[-1].get('day', '')))}</text>"
        )
        parts.append(
            f'<text x="{pad - 6}" y="{pad + 4}" font-size="10" text-anchor="end" '
            f'fill="#4a5568">{scale}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
