"""Append-only SQLite journal with checksummed frames.

The storage layer is the durable spine of mnemofold.  Every event is
written to a ``frames`` table as a single row with:

- a monotonic ``seq`` (auto-incremented primary key),
- the full event envelope JSON,
- a SHA-256 checksum of the envelope,
- the checksum of the previous frame, forming a hash chain.

The chain property means that any truncation or tampering can be
detected by replaying from the beginning.  The journal is the source of
truth — projections (graphs, indexes, summaries) are rebuilt from the
journal on every open, guaranteeing identical state for identical input.

Schema migrations are versioned and applied on open.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from mnemofold.events import Event

SCHEMA_VERSION = 3  # Bump when migrations are added

_INIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS frames (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    prev_chain_checksum TEXT NOT NULL,
    chain_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_frames_event_type ON frames(event_type);
CREATE INDEX IF NOT EXISTS idx_frames_timestamp ON frames(timestamp);
CREATE INDEX IF NOT EXISTS idx_frames_event_id ON frames(event_id);

CREATE TABLE IF NOT EXISTS tombstones (
    event_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    deleted_at TEXT NOT NULL
);
"""


def _migrate_2_to_3(cur: sqlite3.Cursor) -> None:
    """v3 adds tombstones so deletions are recorded inside the journal."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tombstones (
            event_id TEXT PRIMARY KEY,
            reason TEXT NOT NULL DEFAULT '',
            deleted_at TEXT NOT NULL
        )
        """
    )


# Migration deltas keyed by the version they migrate FROM. A journal at
# version N is stepped through N, N+1, ... until it reaches the current
# SCHEMA_VERSION; a missing step is a hard error rather than silent drift.
MIGRATIONS: dict[int, Callable[[sqlite3.Cursor], None]] = {
    2: _migrate_2_to_3,
}


def _frame_chain_checksum(prev_chain: str, envelope_json: str) -> str:
    """Compute the chain checksum for a frame.

    Chain checksum = SHA-256(prev_chain_checksum || envelope_json)
    where || is concatenation with a newline separator.
    """
    blob = f"{prev_chain}\n{envelope_json}".encode()
    return hashlib.sha256(blob).hexdigest()


def _genesis_chain_checksum() -> str:
    """The chain checksum before any frames are written."""
    return hashlib.sha256(b"mnemofold_genesis_v1").hexdigest()


@dataclass
class FrameInfo:
    """Metadata about a frame in the journal."""

    seq: int
    event_id: str
    event_type: str
    timestamp: datetime
    chain_checksum: str
    prev_chain_checksum: str


@dataclass
class ChainAudit:
    """Result of walking the journal hash chain frame by frame."""

    checked: int
    first_bad_seq: int | None

    @property
    def ok(self) -> bool:
        return self.first_bad_seq is None


@dataclass
class Tombstone:
    """Journal record that an event id was deleted (right-to-forget).

    Tombstones are markers, not removals: the frame stays in the chain so
    the journal remains verifiable, while every consumer can check that
    the event must no longer surface.
    """

    event_id: str
    reason: str
    deleted_at: datetime


class Journal:
    """Append-only SQLite event journal.

    All writes happen through :meth:`append`, which is idempotent
    (duplicate ``event_id`` is silently ignored).  The journal uses a
    hash chain so the entire history can be verified for tampering.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._apply_schema()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema + migrations
    # ------------------------------------------------------------------

    def _apply_schema(self) -> None:
        with self._transaction() as cur:
            cur.executescript(_INIT_SCHEMA_SQL)
            # Record or verify schema version
            cur.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
            else:
                stored = int(row[0])
                if stored > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Journal schema version {stored} is newer than "
                        f"code version {SCHEMA_VERSION}"
                    )
                version = stored
                while version < SCHEMA_VERSION:
                    migrate = MIGRATIONS.get(version)
                    if migrate is None:
                        raise RuntimeError(f"no migration path from schema version {version}")
                    migrate(cur)
                    version += 1
                if stored < SCHEMA_VERSION:
                    cur.execute(
                        "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                        (str(SCHEMA_VERSION),),
                    )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for a single transaction."""
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def append(self, event: Event) -> bool:
        """Append an event to the journal.

        Returns True if the event was newly written, False if it was
        already present.  The write is atomic — either the frame is
        fully persisted or the journal is unchanged.
        """
        envelope_json = event.to_json()

        with self._transaction() as cur:
            # Check for duplicate
            cur.execute("SELECT 1 FROM frames WHERE event_id = ?", (event.event_id,))
            if cur.fetchone() is not None:
                return False

            # Get the last chain checksum
            cur.execute("SELECT chain_checksum FROM frames ORDER BY seq DESC LIMIT 1")
            row = cur.fetchone()
            prev_chain = row[0] if row else _genesis_chain_checksum()
            chain_checksum = _frame_chain_checksum(prev_chain, envelope_json)

            now = datetime.now(UTC).isoformat()
            cur.execute(
                """
                INSERT INTO frames
                    (event_id, event_type, timestamp, envelope_json,
                     content_checksum, prev_chain_checksum, chain_checksum,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.timestamp.isoformat(),
                    envelope_json,
                    event.content_checksum,
                    prev_chain,
                    chain_checksum,
                    now,
                ),
            )
            return True

    def extend(self, events: list[Event]) -> int:
        """Append multiple events in one all-or-nothing transaction.

        Duplicates are skipped and do not break the chain. If any insert
        fails midway the whole batch rolls back and the journal stays
        exactly as it was. Returns the number of newly written events.
        """
        written = 0
        with self._transaction() as cur:
            cur.execute("SELECT chain_checksum FROM frames ORDER BY seq DESC LIMIT 1")
            row = cur.fetchone()
            prev_chain = row[0] if row else _genesis_chain_checksum()
            for event in events:
                cur.execute("SELECT 1 FROM frames WHERE event_id = ?", (event.event_id,))
                if cur.fetchone() is not None:
                    continue
                envelope_json = event.to_json()
                chain_checksum = _frame_chain_checksum(prev_chain, envelope_json)
                cur.execute(
                    """
                    INSERT INTO frames
                        (event_id, event_type, timestamp, envelope_json,
                         content_checksum, prev_chain_checksum, chain_checksum,
                         created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type.value,
                        event.timestamp.isoformat(),
                        envelope_json,
                        event.content_checksum,
                        prev_chain,
                        chain_checksum,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                prev_chain = chain_checksum
                written += 1
        return written

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM frames")
        return int(cur.fetchone()[0])

    def __contains__(self, event_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM frames WHERE event_id = ?", (event_id,))
        return cur.fetchone() is not None

    def get(self, event_id: str) -> Event | None:
        cur = self._conn.execute("SELECT envelope_json FROM frames WHERE event_id = ?", (event_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Event.from_json(row[0])

    def __iter__(self) -> Iterator[Event]:
        return self.iter_events()

    def iter_events(self, *, reverse: bool = False) -> Iterator[Event]:
        """Iterate events in seq order (or reverse)."""
        order = "DESC" if reverse else "ASC"
        cur = self._conn.execute(f"SELECT envelope_json FROM frames ORDER BY seq {order}")
        for (envelope_json,) in cur:
            yield Event.from_json(envelope_json)

    def frame_info(self, seq: int) -> FrameInfo | None:
        """Return metadata for the frame at the given sequence number."""
        cur = self._conn.execute(
            "SELECT seq, event_id, event_type, timestamp, chain_checksum, prev_chain_checksum "
            "FROM frames WHERE seq = ?",
            (seq,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return FrameInfo(
            seq=row[0],
            event_id=row[1],
            event_type=row[2],
            timestamp=datetime.fromisoformat(row[3]),
            chain_checksum=row[4],
            prev_chain_checksum=row[5],
        )

    def last_seq(self) -> int:
        """Return the sequence number of the last frame, or 0 if empty."""
        cur = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM frames")
        return int(cur.fetchone()[0])

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> bool:
        """True when every frame's chain checksum verifies (see audit_chain)."""
        return self.audit_chain().ok

    def audit_chain(self) -> ChainAudit:
        """Walk the hash chain and report the first broken frame, if any.

        Unlike :meth:`verify_chain` this tells callers *where* the chain
        breaks and how many frames were checked, which is what repair
        tooling and CLI audits need.
        """
        prev = _genesis_chain_checksum()
        checked = 0
        cur = self._conn.execute(
            "SELECT seq, envelope_json, chain_checksum FROM frames ORDER BY seq ASC"
        )
        for seq, envelope_json, stored in cur:
            checked += 1
            if _frame_chain_checksum(prev, envelope_json) != stored:
                return ChainAudit(checked=checked, first_bad_seq=int(seq))
            prev = stored
        return ChainAudit(checked=checked, first_bad_seq=None)

    def head_checksum(self) -> str:
        """Return the chain checksum of the last frame, or genesis if empty."""
        cur = self._conn.execute("SELECT chain_checksum FROM frames ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            return _genesis_chain_checksum()
        return row[0]

    def stats(self) -> dict[str, Any]:
        """Operational counters for dashboards and integrity reports.

        Read-only and deterministic: frame and tombstone counts, the
        current chain head, and the schema version the file is on.
        """
        row = self._conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()
        return {
            "frames": len(self),
            "tombstones": int(row[0]) if row else 0,
            "head_checksum": self.head_checksum(),
            "schema_version": SCHEMA_VERSION,
        }

    # ------------------------------------------------------------------
    # Tombstones
    # ------------------------------------------------------------------

    def record_tombstone(self, event_id: str, reason: str = "") -> bool:
        """Mark ``event_id`` as deleted. First record wins; returns whether
        a new tombstone was written."""
        with self._transaction() as cur:
            cur.execute("SELECT 1 FROM tombstones WHERE event_id = ?", (event_id,))
            if cur.fetchone() is not None:
                return False
            cur.execute(
                "INSERT INTO tombstones (event_id, reason, deleted_at) VALUES (?, ?, ?)",
                (event_id, reason, datetime.now(UTC).isoformat()),
            )
            return True

    def tombstone(self, event_id: str) -> Tombstone | None:
        """Return the tombstone for an event id, or None if it is not marked."""
        cur = self._conn.execute(
            "SELECT event_id, reason, deleted_at FROM tombstones WHERE event_id = ?",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Tombstone(event_id=row[0], reason=row[1], deleted_at=datetime.fromisoformat(row[2]))

    def iter_tombstones(self) -> Iterator[Tombstone]:
        """All tombstones ordered by event id (deterministic)."""
        cur = self._conn.execute(
            "SELECT event_id, reason, deleted_at FROM tombstones ORDER BY event_id ASC"
        )
        for event_id, reason, deleted_at in cur:
            yield Tombstone(event_id, reason, datetime.fromisoformat(deleted_at))

    # ------------------------------------------------------------------
    # Projections
    # ------------------------------------------------------------------

    def project(self, factory: Callable[[], _ProjectionT]) -> _ProjectionT:
        """Rebuild a projection by folding every frame in seq order.

        Projections are derived state: the journal is the source of truth,
        so folding the same journal twice (or on two machines, or after a
        reopen) must always produce an identical digest.
        """
        projection = factory()
        for event in self.iter_events():
            projection.apply(event)
        return projection


class Projection(Protocol):
    """A deterministic fold over journal events."""

    def apply(self, event: Event) -> None: ...

    def digest(self) -> str: ...


_ProjectionT = TypeVar("_ProjectionT", bound=Projection)


@dataclass
class EventStatsProjection:
    """Reference projection: per-type counts, id order, and time bounds."""

    counts: dict[str, int] = field(default_factory=dict)
    event_ids: list[str] = field(default_factory=list)
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    def apply(self, event: Event) -> None:
        kind = event.event_type.value
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.event_ids.append(event.event_id)
        if self.first_timestamp is None or event.timestamp < self.first_timestamp:
            self.first_timestamp = event.timestamp
        if self.last_timestamp is None or event.timestamp > self.last_timestamp:
            self.last_timestamp = event.timestamp

    def digest(self) -> str:
        payload = {
            "counts": self.counts,
            "event_ids": self.event_ids,
            "first": self.first_timestamp.isoformat() if self.first_timestamp else None,
            "last": self.last_timestamp.isoformat() if self.last_timestamp else None,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
