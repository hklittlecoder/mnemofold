"""Access log summary aggregation."""

from datetime import UTC, datetime

from mnemofold.privacy import AccessLog, AccessLogEntry


def entry(principal: str, action: str, granted: bool, minute: int) -> AccessLogEntry:
    return AccessLogEntry(
        timestamp=datetime(2026, 3, 1, 9, minute, tzinfo=UTC),
        principal=principal,
        action=action,
        resource_id=f"mem-{minute}",
        granted=granted,
        reason="tier check",
    )


class TestAccessLogSummary:
    def test_empty_log(self):
        summary = AccessLog().summary()
        assert summary["total"] == 0
        assert summary["first"] is None and summary["last"] is None
        assert summary["by_principal"] == {}

    def test_counts_by_principal_and_action(self):
        log = AccessLog()
        log.record(entry("ana", "read", True, 0))
        log.record(entry("ana", "export", False, 1))
        log.record(entry("bo", "read", True, 2))
        summary = log.summary()
        assert summary["total"] == 3
        assert summary["granted"] == 2
        assert summary["denied"] == 1
        assert summary["by_principal"] == {"ana": 2, "bo": 1}
        assert summary["by_action"] == {"export": 1, "read": 2}

    def test_bounds_are_recorded(self):
        log = AccessLog()
        log.record(entry("ana", "read", True, 5))
        log.record(entry("ana", "read", True, 9))
        summary = log.summary()
        assert summary["first"] == "2026-03-01T09:05:00+00:00"
        assert summary["last"] == "2026-03-01T09:09:00+00:00"

    def test_summary_survives_export_roundtrip(self):
        log = AccessLog()
        log.record(entry("ana", "read", True, 0))
        log.record(entry("bo", "write", False, 1))
        rebuilt = AccessLog.import_jsonl(log.export_jsonl())
        assert rebuilt.summary() == log.summary()

    def test_deterministic(self):
        log = AccessLog()
        log.record(entry("ana", "read", True, 0))
        assert log.summary() == log.summary()
