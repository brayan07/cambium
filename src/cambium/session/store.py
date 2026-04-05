"""SQLite persistence for sessions and messages."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from cambium.session.model import Session, SessionMessage, SessionOrigin, SessionStatus


class SessionStore:
    """Stores sessions and their messages in SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                origin TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                routine_name TEXT,
                adapter_instance_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_status
                ON sessions(status);

            CREATE TABLE IF NOT EXISTS session_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_session_messages_session
                ON session_messages(session_id, sequence);
        """)

    def create_session(self, session: Session) -> None:
        self._conn.execute(
            "INSERT INTO sessions (id, origin, status, routine_name, "
            "adapter_instance_name, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.origin.value,
                session.status.value,
                session.routine_name,
                session.adapter_instance_name,
                session.created_at,
                session.updated_at,
                json.dumps(session.metadata),
            ),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT id, origin, status, routine_name, adapter_instance_name, "
            "created_at, updated_at, metadata FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return Session(
            id=row[0],
            origin=SessionOrigin(row[1]),
            status=SessionStatus(row[2]),
            routine_name=row[3],
            adapter_instance_name=row[4],
            created_at=row[5],
            updated_at=row[6],
            metadata=json.loads(row[7]),
        )

    def update_status(self, session_id: str, status: SessionStatus) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, session_id),
        )
        self._conn.commit()

    def update_metadata(self, session_id: str, metadata: dict) -> None:
        """Merge keys into existing session metadata."""
        from datetime import datetime, timezone

        session = self.get_session(session_id)
        if session is None:
            return
        merged = {**session.metadata, **metadata}
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE sessions SET metadata = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), now, session_id),
        )
        self._conn.commit()

    def list_sessions(
        self,
        status: SessionStatus | None = None,
        origin: SessionOrigin | None = None,
        limit: int = 50,
    ) -> list[Session]:
        query = "SELECT id, origin, status, routine_name, adapter_instance_name, created_at, updated_at, metadata FROM sessions"
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if origin is not None:
            conditions.append("origin = ?")
            params.append(origin.value)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [
            Session(
                id=r[0],
                origin=SessionOrigin(r[1]),
                status=SessionStatus(r[2]),
                routine_name=r[3],
                adapter_instance_name=r[4],
                created_at=r[5],
                updated_at=r[6],
                metadata=json.loads(r[7]),
            )
            for r in rows
        ]

    def add_message(self, message: SessionMessage) -> None:
        self._conn.execute(
            "INSERT INTO session_messages (id, session_id, role, content, "
            "created_at, sequence, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                message.id,
                message.session_id,
                message.role,
                message.content,
                message.created_at,
                message.sequence,
                json.dumps(message.metadata),
            ),
        )
        self._conn.commit()

    def get_messages(
        self, session_id: str, after_sequence: int = -1, limit: int = 100
    ) -> list[SessionMessage]:
        rows = self._conn.execute(
            "SELECT id, session_id, role, content, created_at, sequence, metadata "
            "FROM session_messages WHERE session_id = ? AND sequence > ? "
            "ORDER BY sequence LIMIT ?",
            (session_id, after_sequence, limit),
        ).fetchall()
        return [
            SessionMessage(
                id=r[0],
                session_id=r[1],
                role=r[2],
                content=r[3],
                created_at=r[4],
                sequence=r[5],
                metadata=json.loads(r[6]),
            )
            for r in rows
        ]

    def next_sequence(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM session_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row[0] if row else 0
