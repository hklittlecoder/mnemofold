"""Golden fixture pinning the journal hash-chain algorithm.

``fixtures/journal_chain_golden.json`` holds the canonical event ids,
per-frame chain checksums, and head digest for a fixed event sequence.
Any change to envelope serialization, chain-checksum derivation, or the
genesis constant makes this test fail, so algorithm drift is deliberate
and reviewed rather than accidental.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mnemofold.events import Event
from mnemofold.storage import Journal

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "journal_chain_golden.json"

T0 = datetime(2025, 4, 1, 8, 0, tzinfo=UTC)


def golden_events() -> list[Event]:
    """Fixed input events for the golden chain fixture."""
    return [
        Event.note(T0, text="open the ledger", author="alice"),
        Event.mail_received(
            T0 + timedelta(minutes=15),
            sender="bob@example.com",
            subject="q2 plan",
            recipients=["alice@example.com"],
            thread_id="th-1",
        ),
        Event.chat_message(
            T0 + timedelta(minutes=40),
            sender="carol",
            body="review is done",
            channel="eng",
        ),
    ]


def golden_payload(db_path: Path) -> str:
    """Canonical JSON text the golden fixture must match byte-for-byte."""
    with Journal(db_path) as journal:
        journal.extend(golden_events())
        infos = []
        for seq in range(1, journal.last_seq() + 1):
            info = journal.frame_info(seq)
            assert info is not None
            infos.append(info)
        payload = {
            "event_ids": [info.event_id for info in infos],
            "chain": [info.chain_checksum for info in infos],
            "head": journal.head_checksum(),
        }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class TestGoldenChain:
    def test_chain_matches_golden_fixture(self, tmp_path):
        assert GOLDEN_PATH.exists(), "golden fixture missing; regenerate it deliberately"
        assert golden_payload(tmp_path / "golden.db") == GOLDEN_PATH.read_text()

    def test_payload_regeneration_is_stable(self, tmp_path):
        first = golden_payload(tmp_path / "a.db")
        second = golden_payload(tmp_path / "b.db")
        assert first == second
