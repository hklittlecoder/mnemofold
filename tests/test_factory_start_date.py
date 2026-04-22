"""Configurable history start dates keep the baseline byte-identical."""

from datetime import UTC, datetime

import pytest

from mnemofold.factory import WorkHistoryFactory


class TestStartDate:
    def test_default_reproduces_baseline(self):
        plain = WorkHistoryFactory(seed=7, days=10).generate()[1]
        explicit = WorkHistoryFactory(seed=7, days=10, start_date="2025-01-01").generate()[1]
        assert plain.checksum == explicit.checksum
        assert explicit.start_date == "2025-01-01T00:00:00+00:00"

    def test_custom_start_recorded_in_manifest(self):
        manifest = WorkHistoryFactory(seed=7, days=10, start_date="2026-03-02").generate()[1]
        assert manifest.start_date == "2026-03-02T00:00:00+00:00"

    def test_custom_start_changes_checksum(self):
        base = WorkHistoryFactory(seed=7, days=10).generate()[1].checksum
        shifted = WorkHistoryFactory(seed=7, days=10, start_date="2026-03-02").generate()[1]
        assert shifted.checksum != base

    def test_naive_start_becomes_utc(self):
        factory = WorkHistoryFactory(seed=7, days=5, start_date="2026-06-01T08:00:00")
        assert factory.start_date.tzinfo is not None
        assert factory.start_date == datetime(2026, 6, 1, 8, 0, tzinfo=UTC)

    def test_offset_start_kept(self):
        factory = WorkHistoryFactory(seed=7, days=5, start_date="2026-06-01T00:00:00+08:00")
        assert factory.start_date.utcoffset().total_seconds() == 8 * 3600

    def test_invalid_start_rejected(self):
        with pytest.raises(ValueError):
            WorkHistoryFactory(seed=7, days=5, start_date="not-a-date")
