"""Workspace-level quiet hours suppress non-critical triggers at night."""

from mnemofold.ledger import Commitment
from mnemofold.workspace import Workspace

DAY = "2026-03-10T10:00:00+00:00"
NIGHT = "2026-03-10T23:00:00+00:00"


def workspace_with_due_soon(tmp_path, **kwargs) -> Workspace:
    ws = Workspace(tmp_path / "ws", **kwargs)
    ws.ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft spec",
            due_date="2026-03-12T10:00:00+00:00",
            created_at=DAY,
        )
    )
    return ws


class TestWorkspaceQuietHours:
    def test_night_tick_suppresses_warning(self, tmp_path):
        ws = workspace_with_due_soon(tmp_path, quiet_hours=(22, 7))
        fired = ws.triggers_tick(NIGHT)
        assert fired, "the reminder still fires..."
        assert all(f.suppressed and f.suppress_reason == "quiet_hours" for f in fired)
        assert ws.trigger_engine.active_triggers() == []
        ws.close()

    def test_day_tick_is_active(self, tmp_path):
        ws = workspace_with_due_soon(tmp_path, quiet_hours=(22, 7))
        fired = ws.triggers_tick(DAY)
        assert any(not f.suppressed for f in fired)
        ws.close()

    def test_default_workspace_has_no_quiet_hours(self, tmp_path):
        ws = workspace_with_due_soon(tmp_path)
        fired = ws.triggers_tick(NIGHT)
        assert any(not f.suppressed for f in fired)
        assert ws.quiet_hours is None
        ws.close()

    def test_critical_overdue_pierces_quiet_hours(self, tmp_path):
        ws = Workspace(tmp_path / "ws", quiet_hours=(22, 7))
        ws.ledger.add(
            Commitment(
                commitment_id="late",
                owed_by="ana",
                owed_to="bo",
                description="overdue spec",
                due_date="2026-03-09T10:00:00+00:00",  # already past at NIGHT
                created_at=DAY,
            )
        )
        fired = ws.triggers_tick(NIGHT)
        critical = [f for f in fired if f.severity.value == "critical"]
        assert critical and all(not f.suppressed for f in critical)
        ws.close()
