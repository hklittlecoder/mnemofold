"""Access log cold-storage export with chain verification on import."""

from datetime import UTC, datetime

from mnemofold.privacy import AccessLog, AccessLogEntry


def entry(i: int, granted: bool = True) -> AccessLogEntry:
    return AccessLogEntry(
        timestamp=datetime(2026, 3, 1, 9, i, tzinfo=UTC),
        principal=f"user{i % 2}",
        action="read",
        resource_id=f"mem-{i}",
        granted=granted,
        reason="tier check",
    )


def make_log(n: int = 4) -> AccessLog:
    log = AccessLog()
    for i in range(n):
        log.record(entry(i, granted=i % 2 == 0))
    return log


class TestAccessLogExport:
    def test_roundtrip_preserves_entries(self):
        log = make_log()
        rebuilt = AccessLog.import_jsonl(log.export_jsonl())
        assert rebuilt.entries() == log.entries()
        assert rebuilt.head_hash() == log.head_hash()
        assert rebuilt.verify()

    def test_export_is_deterministic(self):
        assert make_log().export_jsonl() == make_log().export_jsonl()

    def test_empty_log_exports_empty_string(self):
        assert AccessLog().export_jsonl() == ""
        assert AccessLog.import_jsonl("").entries() == []

    def test_export_is_one_canonical_line_per_entry(self):
        log = make_log(3)
        lines = log.export_jsonl().splitlines()
        assert len(lines) == 3
        for line in lines:
            assert '", "' not in line  # compact separators
            assert '": ' not in line

    def test_blank_lines_tolerated_on_import(self):
        log = make_log(2)
        padded = "\n" + log.export_jsonl() + "\n\n"
        assert len(AccessLog.import_jsonl(padded).entries()) == 2
