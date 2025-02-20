from datetime import date

from mnemofold.reports import (
    FoldSummaryItem,
    TimelineItem,
    escape_text,
    render_fold_summary_svg,
    render_markdown_heading,
    render_markdown_list,
    render_markdown_table,
    render_metric_table,
    render_timeline_svg,
    render_workload_strip,
    wrap_html,
)


def test_escape_text_basic():
    assert escape_text("hello") == "hello"


def test_escape_text_html():
    assert (
        escape_text("<script>alert('x')</script>")
        == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )


def test_escape_text_quotes():
    result = escape_text('"quoted"')
    assert "&quot;" in result
    assert '"' not in result


def test_render_markdown_heading():
    assert render_markdown_heading("Hello") == "# Hello"
    assert render_markdown_heading("Sub", level=2) == "## Sub"


def test_render_markdown_list():
    result = render_markdown_list(["a", "b", "c"])
    assert result == "- a\n- b\n- c"


def test_render_markdown_list_empty():
    assert render_markdown_list([]) == ""


def test_render_markdown_table():
    headers = ["Name", "Value"]
    rows = [["a", "1"], ["b", "2"]]
    result = render_markdown_table(headers, rows)
    lines = result.split("\n")
    assert len(lines) == 4
    assert "| Name | Value |" in lines[0]
    assert "| --- | --- |" in lines[1]
    assert "| a | 1 |" in lines[2]
    assert "| b | 2 |" in lines[3]


def test_render_workload_strip_basic():
    svg = render_workload_strip([3, 7, 2, 5, 8])
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "rect" in svg
    # 5 bars
    assert svg.count("<rect") == 5


def test_render_workload_strip_empty():
    assert render_workload_strip([]) == ""


def test_render_workload_strip_contains_label():
    svg = render_workload_strip([1, 2, 3])
    assert "3 days" in svg
    assert "max=3" in svg


def test_render_timeline_svg_basic():
    items = [
        TimelineItem("Task A", date(2026, 1, 1), date(2026, 1, 5), "open"),
        TimelineItem("Task B", date(2026, 1, 3), date(2026, 1, 10), "done"),
        TimelineItem("Task C", date(2026, 1, 2), date(2026, 1, 8), "overdue"),
    ]
    svg = render_timeline_svg(items)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "Task A" in svg
    assert "Task B" in svg
    assert "Task C" in svg
    # Three bars
    assert svg.count("<rect") == 3


def test_render_timeline_svg_empty():
    assert render_timeline_svg([]) == ""


def test_render_timeline_svg_colors():
    items = [
        TimelineItem("A", date(2026, 1, 1), date(2026, 1, 2), "open"),
        TimelineItem("B", date(2026, 1, 1), date(2026, 1, 2), "done"),
        TimelineItem("C", date(2026, 1, 1), date(2026, 1, 2), "overdue"),
        TimelineItem("D", date(2026, 1, 1), date(2026, 1, 2), "cancelled"),
    ]
    svg = render_timeline_svg(items)
    assert "#4a90d9" in svg  # open
    assert "#4caf50" in svg  # done
    assert "#e53935" in svg  # overdue
    assert "#9e9e9e" in svg  # cancelled


def test_render_timeline_svg_escapes_labels():
    items = [
        TimelineItem("<evil>", date(2026, 1, 1), date(2026, 1, 2), "open"),
    ]
    svg = render_timeline_svg(items)
    assert "&lt;evil&gt;" in svg
    assert "<evil>" not in svg


def test_render_fold_summary_svg():
    items = [
        FoldSummaryItem("meetings", 10, merged=3),
        FoldSummaryItem("mail_threads", 20, merged=8),
        FoldSummaryItem("notes", 5, merged=1),
    ]
    svg = render_fold_summary_svg(items)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "meetings" in svg
    assert "mail_threads" in svg
    # Each item has total bar + merged bar = 2 rects per item, 6 total
    assert svg.count("<rect") == 6


def test_render_fold_summary_empty():
    assert render_fold_summary_svg([]) == ""


def test_wrap_html_structure():
    html_out = wrap_html(
        "Test Report",
        [("Section 1", "<p>Content</p>"), ("Section 2", "<p>More</p>")],
    )
    assert html_out.startswith("<!DOCTYPE html>")
    assert "<title>Test Report</title>" in html_out
    assert "<h1>Test Report</h1>" in html_out
    assert "Section 1" in html_out
    assert "Section 2" in html_out
    assert "</html>" in html_out


def test_wrap_html_escapes_title():
    html_out = wrap_html("<Bad Title>", [])
    assert "&lt;Bad Title&gt;" in html_out
    assert "<Bad Title>" not in html_out


def test_wrap_html_escapes_section_headings():
    html_out = wrap_html("T", [("<Script>", "content")])
    assert "&lt;Script&gt;" in html_out
    assert "<Script>" not in html_out


def test_render_metric_table():
    metrics = [("precision", 0.95, "pass"), ("recall", 0.80, "warn")]
    html_out = render_metric_table(metrics)
    assert "<table>" in html_out
    assert "precision" in html_out
    assert "0.9500" in html_out
    assert "recall" in html_out
    assert "0.8000" in html_out
    assert "status-pass" in html_out
    assert "status-warn" in html_out


def test_render_metric_table_escapes_names():
    html_out = render_metric_table([("<evil>", 0.5, "pass")])
    assert "&lt;evil&gt;" in html_out
    assert "<evil>" not in html_out
