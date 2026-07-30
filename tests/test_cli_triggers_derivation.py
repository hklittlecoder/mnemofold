"""Deterministic derivation through the CLI: stale + unanswered threads.

Two threaded events are journaled — an old thread ending in a question
and a fresh thread — then the CLI tick must fire exactly the stale and
follow-up rules for the old thread and nothing for the fresh one.
"""

import json
from datetime import UTC, datetime, timedelta

from mnemofold.cli import main
from mnemofold.events import Event, EventType
from mnemofold.workspace import Workspace

NOW_DT = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
NOW = NOW_DT.isoformat()
OLD = (NOW_DT - timedelta(days=4)).isoformat()
FRESH = (NOW_DT - timedelta(hours=1)).isoformat()


def build_db(tmp_path):
    db = tmp_path / "ws"
    ws = Workspace(db)
    ws.ingest_events(
        [
            Event(
                event_type=EventType.MAIL_RECEIVED,
                timestamp=NOW_DT - timedelta(days=4),
                content={"thread_id": "t-old", "subject": "release", "body": "any update?"},
            ),
            Event(
                event_type=EventType.MAIL_RECEIVED,
                timestamp=NOW_DT - timedelta(hours=1),
                content={"thread_id": "t-fresh", "subject": "lunch", "body": "pizza?"},
            ),
        ],
        now=NOW,
    )
    ws.close()
    return db


class TestTriggersDerivation:
    def test_stale_and_followup_fire_for_old_thread(self, tmp_path, capsys):
        db = build_db(tmp_path)
        capsys.readouterr()
        rc = main(["triggers", "--db", str(db), "--now", NOW, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        pairs = {(entry["kind"], entry["target_id"]) for entry in payload}
        assert ("stale_thread", "t-old") in pairs
        assert ("follow_up", "t-old") in pairs

    def test_fresh_thread_stays_quiet(self, tmp_path, capsys):
        db = build_db(tmp_path)
        capsys.readouterr()
        main(["triggers", "--db", str(db), "--now", NOW, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert all(entry["target_id"] != "t-fresh" for entry in payload)

    def test_default_now_uses_last_event(self, tmp_path, capsys):
        db = build_db(tmp_path)
        capsys.readouterr()
        rc = main(["triggers", "--db", str(db), "--json"])
        assert rc == 0
        # with now == last event, the old thread is stale by ~4 days still
        payload = json.loads(capsys.readouterr().out)
        kinds = {entry["kind"] for entry in payload}
        assert "stale_thread" in kinds

    def test_repeated_invocations_are_deterministic(self, tmp_path, capsys):
        # each CLI run derives a fresh engine, so identical inputs must
        # produce identical fired-trigger payloads across invocations
        db = build_db(tmp_path)
        capsys.readouterr()
        main(["triggers", "--db", str(db), "--now", NOW, "--json"])
        first = json.loads(capsys.readouterr().out)
        main(["triggers", "--db", str(db), "--now", NOW, "--json"])
        second = json.loads(capsys.readouterr().out)
        assert first == second
