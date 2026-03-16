"""An edited export must be rejected line-precisely, never half-imported."""

from datetime import UTC, datetime

import pytest

from mnemofold.privacy import AccessLog, AccessLogEntry


def make_log(n: int = 4) -> AccessLog:
    log = AccessLog()
    for i in range(n):
        log.record(
            AccessLogEntry(
                timestamp=datetime(2026, 3, 1, 9, i, tzinfo=UTC),
                principal="ana",
                action="read",
                resource_id=f"mem-{i}",
                granted=True,
                reason="tier check",
            )
        )
    return log


class TestExportTamperDetection:
    def test_flipped_grant_is_rejected(self):
        text = make_log().export_jsonl()
        lines = text.splitlines()
        lines[2] = lines[2].replace('"granted":true', '"granted":false')
        with pytest.raises(ValueError, match="line 3"):
            AccessLog.import_jsonl("\n".join(lines))

    def test_edited_reason_is_rejected(self):
        text = make_log().export_jsonl()
        tampered = text.replace("tier check", "admin override", 1)
        with pytest.raises(ValueError, match="chain mismatch"):
            AccessLog.import_jsonl(tampered)

    def test_reordered_lines_are_rejected(self):
        lines = make_log().export_jsonl().splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        with pytest.raises(ValueError, match="chain mismatch"):
            AccessLog.import_jsonl("\n".join(lines))

    def test_dropped_line_breaks_the_chain(self):
        lines = make_log(4).export_jsonl().splitlines()
        with pytest.raises(ValueError, match="chain mismatch"):
            AccessLog.import_jsonl("\n".join([lines[0], lines[2], lines[3]]))

    def test_failed_import_leaves_no_partial_log(self):
        text = make_log().export_jsonl()
        lines = text.splitlines()
        lines[1] = lines[1].replace('"ana"', '"mallory"')
        with pytest.raises(ValueError):
            AccessLog.import_jsonl("\n".join(lines))
        # the honest log still imports cleanly
        assert len(AccessLog.import_jsonl(text).entries()) == 4
