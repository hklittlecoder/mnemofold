"""Seeded random sessions must be fully reproducible from the journal.

Each run performs a random sequence of remember/forget/ask operations,
snapshots the workspace, rebuilds every projection from the journal,
and demands a byte-identical snapshot plus a clean integrity report —
the core durability promise, randomized.
"""

import random

from mnemofold.workspace import Workspace


class TestRebuildParity:
    def test_random_sessions_replay_identically(self, tmp_path):
        for seed in range(6):
            rng = random.Random(seed)
            ws = Workspace(tmp_path / f"ws{seed}")
            ids: list[str] = []
            for clock in range(1, 15):
                now = f"2026-03-{(clock % 27) + 1:02d}T{(clock % 23):02d}:30:00+00:00"
                roll = rng.random()
                if roll < 0.55 or not ids:
                    ids.append(
                        ws.remember(
                            f"note {seed}-{clock} about release planning",
                            title=f"n{clock}",
                            tags=["sweep"] if clock % 3 == 0 else [],
                            now=now,
                        )
                    )
                elif roll < 0.85:
                    ws.forget(rng.choice(ids), now=now, reason="sweep")
                else:
                    ws.ask("release", now=now)
            before = ws.snapshot()
            ws.rebuild()
            after = ws.snapshot()
            assert before == after, seed
            assert ws.verify_integrity()["ok"] is True, seed
            ws.close()

    def test_rebuild_is_idempotent_twice(self, tmp_path):
        ws = Workspace(tmp_path / "twice")
        ws.remember("alpha note", now="2026-03-01T09:00:00+00:00")
        ws.rebuild()
        first = ws.snapshot()
        ws.rebuild()
        assert ws.snapshot() == first
        ws.close()
