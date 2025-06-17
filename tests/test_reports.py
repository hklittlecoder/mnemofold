from datetime import date

from mnemofold.reports import (
    FoldSummaryItem,
    TimelineItem,
    assemble_report_page,
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


def test_timeline_legend_off_by_default():
    items = [TimelineItem("A", date(2026, 1, 1), date(2026, 1, 2), "open")]
    svg = render_timeline_svg(items)
    assert svg.count("<rect") == 1  # the bar only


def test_timeline_legend_adds_chips_for_used_statuses():
    items = [
        TimelineItem("A", date(2026, 1, 1), date(2026, 1, 2), "open"),
        TimelineItem("B", date(2026, 1, 1), date(2026, 1, 2), "done"),
    ]
    svg = render_timeline_svg(items, legend=True)
    assert svg.count("<rect") == 4  # 2 bars + 2 legend chips
    assert ">open</text>" in svg
    assert ">done</text>" in svg
    assert ">overdue</text>" not in svg  # unused statuses are not drawn


def test_timeline_legend_grows_canvas():
    items = [TimelineItem("A", date(2026, 1, 1), date(2026, 1, 2), "open")]
    plain = render_timeline_svg(items)
    with_legend = render_timeline_svg(items, legend=True)
    assert len(with_legend) > len(plain)
    assert 'height="54"' in plain
    assert 'height="76"' in with_legend


def test_timeline_legend_is_deterministic():
    items = [
        TimelineItem("A", date(2026, 1, 1), date(2026, 1, 3), "overdue"),
        TimelineItem("B", date(2026, 1, 2), date(2026, 1, 4), "open"),
    ]
    assert render_timeline_svg(items, legend=True) == render_timeline_svg(items, legend=True)


def test_report_page_contains_all_given_sections():
    page = assemble_report_page(
        "Weekly",
        timeline_items=[TimelineItem("A", date(2026, 1, 1), date(2026, 1, 2), "open")],
        fold_items=[FoldSummaryItem("semantic", 5, 2)],
        day_counts=[1, 2, 3],
        metrics=[("precision", 0.75, "ok")],
        run_metadata={"seed": "9", "version": "0.1.0"},
    )
    assert page.startswith("<!DOCTYPE html>")
    assert "Commitment timeline" in page
    assert "Folding summary" in page
    assert "Workload" in page
    assert "Metrics" in page
    assert "Run metadata" in page
    assert "<svg" in page
    assert "precision" in page
    assert "0.1.0" in page


def test_report_page_omits_absent_sections():
    page = assemble_report_page("Weekly", day_counts=[1, 2])
    assert "Commitment timeline" not in page
    assert "Folding summary" not in page
    assert "Metrics" not in page
    assert "Workload" in page
    assert "Run metadata" not in page


def test_report_page_escapes_metadata_values():
    page = assemble_report_page("T", run_metadata={"note": "<script>x</script>"})
    assert "<script>x" not in page
    assert "&lt;script&gt;" in page


def test_report_page_metadata_rows_sorted():
    page = assemble_report_page("T", run_metadata={"zeta": "1", "alpha": "2"})
    assert page.index(">alpha<") < page.index(">zeta<")


def test_report_page_has_no_scripts_and_is_deterministic():
    args = {
        "timeline_items": [TimelineItem("A", date(2026, 1, 1), date(2026, 1, 2), "done")],
        "day_counts": [2, 4],
        "run_metadata": {"seed": "1"},
    }
    first = assemble_report_page("T", **args)
    second = assemble_report_page("T", **args)
    assert first == second
    assert "<script" not in first
