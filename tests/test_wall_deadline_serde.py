"""Wall-clock deadline serialization and field validation."""

from datetime import UTC, datetime

import pytest

from mnemofold.temporal import WallDeadline, wall_deadline_in


class TestWallDeadlineSerde:
    def test_roundtrip_preserves_instant(self):
        original = wall_deadline_in("us", "2026-03-14", 17, 30)
        rebuilt = WallDeadline.from_dict(original.to_dict())
        assert rebuilt == original
        assert rebuilt.instant() == original.instant()

    def test_to_dict_shape(self):
        d = wall_deadline_in("hk", "2026-05-01", 9).to_dict()
        assert d == {
            "day": "2026-05-01",
            "hour": 9,
            "minute": 0,
            "region_tz": "Asia/Hong_Kong",
        }

    def test_bad_day_rejected(self):
        with pytest.raises(ValueError):
            WallDeadline.from_dict(
                {"day": "2026-13-45", "hour": 9, "minute": 0, "region_tz": "UTC"}
            )

    def test_hour_out_of_range_rejected(self):
        for hour in (-1, 24):
            with pytest.raises(ValueError, match="hour"):
                WallDeadline.from_dict(
                    {"day": "2026-03-14", "hour": hour, "minute": 0, "region_tz": "UTC"}
                )

    def test_minute_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="minute"):
            WallDeadline.from_dict(
                {"day": "2026-03-14", "hour": 9, "minute": 60, "region_tz": "UTC"}
            )

    def test_unknown_zone_rejected_as_value_error(self):
        with pytest.raises(ValueError, match="IANA"):
            WallDeadline.from_dict(
                {
                    "day": "2026-03-14",
                    "hour": 9,
                    "minute": 0,
                    "region_tz": "Mars/Olympus",
                }
            )

    def test_missing_field_raises_key_error(self):
        with pytest.raises(KeyError):
            WallDeadline.from_dict({"day": "2026-03-14", "hour": 9, "minute": 0})

    def test_overdue_survives_roundtrip(self):
        original = wall_deadline_in("de", "2026-06-01", 12)
        rebuilt = WallDeadline.from_dict(original.to_dict())
        now = datetime(2026, 6, 1, 12, 0, 1, tzinfo=UTC).astimezone(original.instant().tzinfo)
        assert original.is_overdue(now) == rebuilt.is_overdue(now)
