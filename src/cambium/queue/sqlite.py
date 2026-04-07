"""SQLite-backed message queue."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from cambium.models.message import Message
from cambium.queue.base import QueueAdapter


class SQLiteQueue(QueueAdapter):
    """SQLite-backed FIFO message queue with at-least-once delivery."""

    def __init__(self, db_path: str = ":memory:", max_attempts: int = 3) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._max_attempts = max_attempts
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                payload TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_status_channel ON messages (status, channel)"
        )
        self._conn.commit()

    def publish(self, message: Message) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (id, channel, payload, source, timestamp, status, attempts) "
                "VALUES (?, ?, ?, ?, ?, 'pending', 0)",
                (
                    message.id,
                    message.channel,
                    json.dumps(message.payload),
                    message.source,
                    message.timestamp.isoformat(),
                ),
            )
            self._conn.commit()

    def consume(self, channels: list[str], limit: int = 1) -> list[Message]:
        if not channels:
            return []
        with self._lock:
            placeholders = ",".join("?" for _ in channels)
            now = datetime.now(timezone.utc).isoformat()

            cursor = self._conn.execute(
                f"SELECT id FROM messages WHERE status = 'pending' AND channel IN ({placeholders}) "
                f"ORDER BY timestamp ASC LIMIT ?",
                (*channels, limit),
            )
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                return []

            id_placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE messages SET status = 'in_flight', claimed_at = ? "
                f"WHERE id IN ({id_placeholders})",
                (now, *ids),
            )
            self._conn.commit()

            cursor = self._conn.execute(
                f"SELECT id, channel, payload, source, timestamp, status, attempts, claimed_at "
                f"FROM messages WHERE id IN ({id_placeholders}) ORDER BY timestamp ASC",
                ids,
            )
            return [self._row_to_message(row) for row in cursor.fetchall()]

    def ack(self, message_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE messages SET status = 'done' WHERE id = ?", (message_id,)
            )
            self._conn.commit()

    def nack(self, message_id: str) -> None:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT attempts FROM messages WHERE id = ?", (message_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return
            new_attempts = row[0] + 1
            if new_attempts >= self._max_attempts:
                self._conn.execute(
                    "UPDATE messages SET status = 'failed', attempts = ? WHERE id = ?",
                    (new_attempts, message_id),
                )
            else:
                self._conn.execute(
                    "UPDATE messages SET status = 'pending', attempts = ?, claimed_at = NULL WHERE id = ?",
                    (new_attempts, message_id),
                )
            self._conn.commit()

    def requeue(self, message_id: str) -> None:
        """Return a consumed message to pending without incrementing attempts."""
        with self._lock:
            self._conn.execute(
                "UPDATE messages SET status = 'pending', claimed_at = NULL WHERE id = ?",
                (message_id,),
            )
            self._conn.commit()

    def pending_count(self, channels: list[str] | None = None) -> int:
        with self._lock:
            if channels is None:
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE status = 'pending'"
                )
            else:
                if not channels:
                    return 0
                placeholders = ",".join("?" for _ in channels)
                cursor = self._conn.execute(
                    f"SELECT COUNT(*) FROM messages WHERE status = 'pending' AND channel IN ({placeholders})",
                    channels,
                )
            return cursor.fetchone()[0]

    def recover_stale_in_flight(self, timeout_seconds: int = 1800) -> int:
        """Reset messages stuck in 'in_flight' longer than timeout back to 'pending'."""
        with self._lock:
            cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds
            # SQLite doesn't have great timestamp math, so fetch and filter in Python.
            cursor = self._conn.execute(
                "SELECT id, claimed_at FROM messages WHERE status = 'in_flight' AND claimed_at IS NOT NULL"
            )
            recovered = 0
            for row in cursor.fetchall():
                try:
                    claimed_ts = datetime.fromisoformat(row[1]).timestamp()
                except (ValueError, TypeError):
                    continue
                if claimed_ts < cutoff:
                    self._conn.execute(
                        "UPDATE messages SET status = 'pending', claimed_at = NULL WHERE id = ?",
                        (row[0],),
                    )
                    recovered += 1
            if recovered:
                self._conn.commit()
            return recovered

    @staticmethod
    def _row_to_message(row: tuple) -> Message:
        return Message(
            id=row[0],
            channel=row[1],
            payload=json.loads(row[2]),
            source=row[3],
            timestamp=datetime.fromisoformat(row[4]),
            status=row[5],
            attempts=row[6],
            claimed_at=datetime.fromisoformat(row[7]) if row[7] else None,
        )
