"""Line-oriented PII scanning for file audits."""

from mnemofold.privacy import scan_lines

LINES = [
    "release notes for march",
    "mail ana.chen@corp.example about the release",
    "call 555-123-4567 or 555-987-6543",
    "",
]


class TestScanLines:
    def test_only_matching_lines_reported(self):
        report = scan_lines(LINES)
        assert [entry["line"] for entry in report] == [2, 3]

    def test_kind_counts(self):
        report = scan_lines(LINES)
        assert report[0]["kinds"] == {"email": 1}
        assert report[1]["kinds"] == {"phone": 2}

    def test_spans_do_not_leak_values(self):
        report = scan_lines(LINES)
        for entry in report:
            for span in entry["spans"]:
                assert set(span) == {"start", "end", "kind"}
                value = LINES[entry["line"] - 1][span["start"] : span["end"]]
                assert value  # spans point at real text...
        # ...but the report itself never contains the raw values
        blob = repr(report)
        assert "ana.chen@corp.example" not in blob
        assert "555-123-4567" not in blob

    def test_empty_input(self):
        assert scan_lines([]) == []
        assert scan_lines(["", "nothing here"]) == []

    def test_deterministic(self):
        assert scan_lines(LINES) == scan_lines(list(LINES))
