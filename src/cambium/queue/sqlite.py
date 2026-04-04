"""SQLite-backed event queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from cambium.models.event import Event
from cambium.queue.base import QueueAdapter


class SQLiteQueue(QueueAdapter):
    """SQLite-backed FIFO event queue with at-least-once delivery."""

    def __init__(self, db_path: str = ":memory:", max_attempts: int = 3) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._max_attempts = max_attempts
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_status_type ON events (status, type)"
        )
        self._conn.commit()

    def enqueue(self, event: Event) -> None:
        """Add an event to the queue."""
        self._conn.execute(
            "INSERT INTO events (id, type, payload, source, timestamp, status, attempts) "
            "VALUES (?, ?, ?, ?, ?, 'pending', 0)",
            (
                event.id,
                event.type,
                json.dumps(event.payload),
                event.source,
                event.timestamp.isoformat(),
            ),
        )
        self._conn.commit()

    def dequeue(self, event_types: list[str], limit: int = 1) -> list[Event]:
        """Atomically claim up to `limit` pending events matching the given types."""
        if not event_types:
            return []
        placeholders = ",".join("?" for _ in event_types)
        now = datetime.now(timezone.utc).isoformat()

        cursor = self._conn.execute(
            f"SELECT id FROM events WHERE status = 'pending' AND type IN ({placeholders}) "
            f"ORDER BY timestamp ASC LIMIT ?",
            (*event_types, limit),
        )
        ids = [row[0] for row in cursor.fetchall()]
        if not ids:
            return []

        id_placeholders = ",".join("?" for _ in ids)
        self._conn.execute(
            f"UPDATE events SET status = 'in_flight', claimed_at = ? "
            f"WHERE id IN ({id_placeholders})",
            (now, *ids),
        )
        self._conn.commit()

        cursor = self._conn.execute(
            f"SELECT id, type, payload, source, timestamp, status, attempts, claimed_at "
            f"FROM events WHERE id IN ({id_placeholders}) ORDER BY timestamp ASC",
            ids,
        )
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def ack(self, event_id: str) -> None:
        """Mark an event as done."""
        self._conn.execute(
            "UPDATE events SET status = 'done' WHERE id = ?", (event_id,)
        )
        self._conn.commit()

    def nack(self, event_id: str) -> None:
        """Return event for retry, or mark failed if max attempts exceeded."""
        cursor = self._conn.execute(
            "SELECT attempts FROM events WHERE id = ?", (event_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return
        new_attempts = row[0] + 1
        if new_attempts >= self._max_attempts:
            self._conn.execute(
                "UPDATE events SET status = 'failed', attempts = ? WHERE id = ?",
                (new_attempts, event_id),
            )
        else:
            self._conn.execute(
                "UPDATE events SET status = 'pending', attempts = ?, claimed_at = NULL WHERE id = ?",
                (new_attempts, event_id),
            )
        self._conn.commit()

    def pending_count(self, event_types: list[str] | None = None) -> int:
        """Count pending events, optionally filtered by type."""
        if event_types is None:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE status = 'pending'"
            )
        else:
            if not event_types:
                return 0
            placeholders = ",".join("?" for _ in event_types)
            cursor = self._conn.execute(
                f"SELECT COUNT(*) FROM events WHERE status = 'pending' AND type IN ({placeholders})",
                event_types,
            )
        return cursor.fetchone()[0]

    @staticmethod
    def _row_to_event(row: tuple) -> Event:
        return Event(
            id=row[0],
            type=row[1],
            payload=json.loads(row[2]),
            source=row[3],
            timestamp=datetime.fromisoformat(row[4]),
            status=row[5],
            attempts=row[6],
            claimed_at=datetime.fromisoformat(row[7]) if row[7] else None,
        )
