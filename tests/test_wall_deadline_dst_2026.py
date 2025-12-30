"""Wall-clock deadlines across the 2026 daylight-saving boundaries.

US transitions: spring forward 2026-03-08, fall back 2026-11-01.
EU transitions: spring forward 2026-03-29, fall back 2026-10-25.
Hong Kong observes no DST. Ambiguous fall-back wall times resolve to
the first occurrence (fold=0), which these tests pin explicitly.
"""

from datetime import UTC, datetime, timedelta

from mnemofold.temporal import CalendarRegistry, wall_deadline_in

REGISTRY = CalendarRegistry.with_defaults(years=(2025, 2026))


class TestDstTransitions:
    def test_us_offset_changes_across_spring_forward(self):
        before = wall_deadline_in("us", "2026-03-07", 16).instant()
        after = wall_deadline_in("us", "2026-03-09", 16).instant()
        assert before.utcoffset() == timedelta(hours=-5)
        assert after.utcoffset() == timedelta(hours=-4)
        assert before.astimezone(UTC).hour == 21
        assert after.astimezone(UTC).hour == 20

    def test_de_offset_changes_across_spring_forward(self):
        before = wall_deadline_in("de", "2026-03-28", 12).instant()
        after = wall_deadline_in("de", "2026-03-30", 12).instant()
        assert before.utcoffset() == timedelta(hours=1)
        assert after.utcoffset() == timedelta(hours=2)

    def test_hk_has_no_dst(self):
        before = wall_deadline_in("hk", "2026-03-07", 12).instant()
        after = wall_deadline_in("hk", "2026-03-09", 12).instant()
        assert before.utcoffset() == after.utcoffset() == timedelta(hours=8)

    def test_ambiguous_fall_back_time_resolves_to_first_occurrence(self):
        # 01:30 in New York happens twice on 2026-11-01; fold=0 means the
        # EDT (first) occurrence, one hour earlier in UTC than the EST one
        ambiguous = wall_deadline_in("us", "2026-11-01", 1, 30).instant()
        assert ambiguous.utcoffset() == timedelta(hours=-4)
        assert ambiguous.astimezone(UTC) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)

    def test_overdue_boundary_is_exclusive_at_the_instant(self):
        deadline = wall_deadline_in("us", "2026-03-09", 16)
        exact = deadline.instant()
        assert not deadline.is_overdue(exact)
        assert deadline.is_overdue(exact + timedelta(seconds=1))
        assert not deadline.is_overdue(exact + timedelta(minutes=30), grace_hours=1.0)

    def test_overdue_compare_across_timezones(self):
        deadline = wall_deadline_in("us", "2026-03-09", 16)
        # 20:00:30 UTC is 16:00:30 EDT — one second-past does not matter,
        # the deadline passed 30 seconds ago
        now_utc = datetime(2026, 3, 9, 20, 0, 30, tzinfo=UTC)
        assert deadline.is_overdue(now_utc)
        hk_now = datetime(2026, 3, 10, 3, 0, 0, tzinfo=UTC)  # 11:00 HKT next day
        assert deadline.is_overdue(hk_now)

    def test_rolled_deadline_keeps_wall_time_across_dst(self):
        # Sat 2026-03-07 rolls to Mon 2026-03-09 — across the spring
        # forward, the wall time stays 16:00 while the UTC hour shifts
        rolled = wall_deadline_in("us", "2026-03-07", 16).rolled_to_workday(REGISTRY.get("us"))
        assert rolled.day == "2026-03-09"
        assert rolled.instant().astimezone(UTC).hour == 20
