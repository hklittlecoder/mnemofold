"""Workspace ticks must track commitment lifecycles, not accumulate ghosts."""

from mnemofold.ledger import Commitment, CommitmentStatus
from mnemofold.workspace import Workspace

T0 = "2026-03-10T10:00:00+00:00"
T1 = "2026-03-11T10:00:00+00:00"  # 24h later: outside the 12h cooldown
T2 = "2026-03-12T10:00:00+00:00"


def workspace_with_commitment(tmp_path, due: str = "2026-03-12T10:00:00+00:00") -> Workspace:
    ws = Workspace(tmp_path / "ws")
    ws.ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft the spec",
            due_date=due,
            created_at=T0,
        )
    )
    return ws


class TestTriggerLifecycle:
    def test_reminder_fires_while_open(self, tmp_path):
        ws = workspace_with_commitment(tmp_path)
        fired = ws.triggers_tick(T0)
        assert any(f.target_id == "c1" for f in fired)
        ws.close()

    def test_completed_commitment_stops_firing(self, tmp_path):
        ws = workspace_with_commitment(tmp_path)
        ws.triggers_tick(T0)
        assert ws.ledger.transition("c1", CommitmentStatus.DONE, T0)
        fired = ws.triggers_tick(T1)  # past cooldown: a ghost rule would fire
        assert not any(f.target_id == "c1" for f in fired)
        assert all(r.rule_id != "trg-c1" for r in ws.trigger_engine.rules())
        ws.close()

    def test_cooldown_still_holds_across_ticks(self, tmp_path):
        ws = workspace_with_commitment(tmp_path)
        first = ws.triggers_tick(T0)
        assert any(f.target_id == "c1" for f in first)
        second = ws.triggers_tick("2026-03-10T12:00:00+00:00")  # 2h later
        assert not any(f.target_id == "c1" for f in second)
        ws.close()

    def test_overdue_alert_replaces_reminder(self, tmp_path):
        ws = workspace_with_commitment(tmp_path, due="2026-03-09T10:00:00+00:00")
        fired = ws.triggers_tick(T0)
        kinds = {f.kind.value for f in fired if f.target_id == "c1"}
        assert kinds == {"overdue_alert"}
        ws.close()

    def test_new_commitment_joins_next_tick(self, tmp_path):
        ws = workspace_with_commitment(tmp_path)
        ws.triggers_tick(T0)
        ws.ledger.add(
            Commitment(
                commitment_id="c2",
                owed_by="bo",
                owed_to="ana",
                description="review the spec",
                due_date="2026-03-12T09:00:00+00:00",
                created_at=T1,
            )
        )
        fired = ws.triggers_tick(T1)
        assert any(f.target_id == "c2" for f in fired)
        ws.close()
