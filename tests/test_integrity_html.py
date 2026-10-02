"""Integrity report rendering: badges, counters, escaping."""

from mnemofold.reports import render_integrity_html

HEALTHY = {
    "ok": True,
    "checks": {
        "journal_chain": True,
        "trace_chain": True,
        "no_resurrection": True,
        "projection_stable": True,
    },
    "frames_checked": 12,
    "first_bad_frame": None,
    "tombstones": 1,
    "resurrected_keys": [],
    "projection_digest": "ab" * 32,
    "journal": {"frames": 12, "tombstones": 1, "schema_version": 3},
}


class TestIntegrityHtml:
    def test_healthy_report(self):
        html = render_integrity_html(HEALTHY)
        assert html.startswith("<!DOCTYPE html>")
        assert "<strong>PASS</strong>" in html
        assert html.count("<td>PASS</td>") == 4
        assert "FAILED" not in html

    def test_failed_report_marks_checks(self):
        broken = dict(HEALTHY)
        broken["ok"] = False
        broken["checks"] = dict(HEALTHY["checks"], no_resurrection=False)
        broken["resurrected_keys"] = ["evt_bad"]
        html = render_integrity_html(broken)
        assert "<strong>FAILED</strong>" in html
        assert "<td>FAILED</td>" in html
        assert "evt_bad" in html

    def test_none_counters_omitted(self):
        html = render_integrity_html(HEALTHY)
        assert "first_bad_frame" not in html  # None-valued counter skipped

    def test_values_are_escaped(self):
        hostile = dict(HEALTHY)
        hostile["projection_digest"] = "<script>alert(1)</script>"
        html = render_integrity_html(hostile)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_minimal_report_renders(self):
        html = render_integrity_html({"ok": True, "checks": {}})
        assert "<strong>PASS</strong>" in html
        assert html.endswith("</html>")

    def test_deterministic(self):
        assert render_integrity_html(HEALTHY) == render_integrity_html(dict(HEALTHY))
