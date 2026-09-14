"""Scan reports stay exact across mixed and repeated content."""

from mnemofold.privacy import RedactionVault, scan_lines


def corpus() -> list[str]:
    return [
        "Subject: invoice 4111 1111 1111 1111 approved",
        "no pii here at all",
        "ana.chen@corp.example cc bo@corp.example",
        "ana.chen@corp.example again",
        "123 Main Street, Springfield stands as the office",
    ]


class TestScanSweep:
    def test_line_numbers_are_one_based_and_ordered(self):
        report = scan_lines(corpus())
        lines = [entry["line"] for entry in report]
        assert lines == sorted(lines)
        assert all(n >= 1 for n in lines)
        assert 2 not in lines  # the clean line is skipped

    def test_repeated_value_reported_per_line(self):
        report = scan_lines(corpus())
        email_lines = [e for e in report if e["kinds"].get("email")]
        assert len(email_lines) == 2

    def test_multi_match_line_counts_all_kinds(self):
        report = scan_lines(corpus())
        first = next(e for e in report if e["line"] == 1)
        assert first["kinds"] == {"credit_card": 1}

    def test_spans_align_with_source(self):
        lines = corpus()
        for entry in scan_lines(lines):
            source = lines[entry["line"] - 1]
            for span in entry["spans"]:
                assert 0 <= span["start"] < span["end"] <= len(source)

    def test_scan_then_seal_covers_everything(self):
        lines = corpus()
        report = scan_lines(lines)
        vault = RedactionVault(salt="sweep")
        sealed = [vault.seal(line) for line in lines]
        # after sealing, a rescan of the sealed text finds nothing
        assert scan_lines(sealed) == []
        assert report  # ... while the original scan did
