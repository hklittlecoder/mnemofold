"""Quiet-hour window edges and how suppression interacts with cooldowns."""

from mnemofold.ledger import Commitment
from mnemofold.workspace import Workspace


def due_soon_workspace(tmp_path, **kwargs) -> Workspace:
    ws = Workspace(tmp_path / "ws", **kwargs)
    ws.ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft spec",
            due_date="2026-03-12T10:00:00+00:00",
            created_at="2026-03-10T09:00:00+00:00",
        )
    )
    return ws


class TestQuietEdges:
    def test_window_boundaries(self, tmp_path):
        ws = due_soon_workspace(tmp_path, quiet_hours=(22, 7))
        quiet = ws.trigger_engine.quiet_hours
        from datetime import UTC, datetime

        assert quiet.is_quiet(datetime(2026, 3, 10, 21, 59, tzinfo=UTC)) is False
        assert quiet.is_quiet(datetime(2026, 3, 10, 22, 0, tzinfo=UTC)) is True
        assert quiet.is_quiet(datetime(2026, 3, 10, 6, 59, tzinfo=UTC)) is True
        assert quiet.is_quiet(datetime(2026, 3, 10, 7, 0, tzinfo=UTC)) is False
        ws.close()

    def test_suppressed_fire_still_arms_cooldown(self, tmp_path):
        ws = due_soon_workspace(tmp_path, quiet_hours=(22, 7))
        night = ws.triggers_tick("2026-03-10T23:00:00+00:00")
        assert night and night[0].suppressed
        # next morning is inside the 12h cooldown of the suppressed fire
        morning = ws.triggers_tick("2026-03-11T08:00:00+00:00")
        assert morning == []
        # after the cooldown the reminder becomes active again
        later = ws.triggers_tick("2026-03-11T12:00:00+00:00")
        assert any(not f.suppressed for f in later)
        ws.close()

    def test_inverted_window_wraps_midnight(self, tmp_path):
        ws = due_soon_workspace(tmp_path, quiet_hours=(23, 5))
        assert ws.triggers_tick("2026-03-10T23:30:00+00:00")[0].suppressed
        ws2 = due_soon_workspace(tmp_path / "b", quiet_hours=(23, 5))
        fired = ws2.triggers_tick("2026-03-10T22:00:00+00:00")
        assert any(not f.suppressed for f in fired)
        ws.close()
        ws2.close()
