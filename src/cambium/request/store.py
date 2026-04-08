"""SQLite persistence for HITL requests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from cambium.request.model import Request, RequestStatus, RequestType


class RequestStore:
    """Stores HITL requests in SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                work_item_id TEXT,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                summary TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                options TEXT,
                "default" TEXT,
                timeout_hours REAL,
                answer TEXT,
                created_at TEXT NOT NULL,
                answered_at TEXT,
                created_by TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_requests_status
                ON requests(status);
            CREATE INDEX IF NOT EXISTS idx_requests_session
                ON requests(session_id);
        """)

    # ── helpers ──────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    _COLS = (
        'id, session_id, work_item_id, type, status, summary, detail, '
        'options, "default", timeout_hours, answer, created_at, answered_at, '
        'created_by'
    )

    def _row_to_request(self, row: tuple) -> Request:
        return Request(
            id=row[0],
            session_id=row[1],
            work_item_id=row[2],
            type=RequestType(row[3]),
            status=RequestStatus(row[4]),
            summary=row[5],
            detail=row[6],
            options=json.loads(row[7]) if row[7] is not None else None,
            default=row[8],
            timeout_hours=row[9],
            answer=row[10],
            created_at=row[11],
            answered_at=row[12],
            created_by=row[13],
        )

    def _request_to_params(self, req: Request) -> tuple:
        return (
            req.id,
            req.session_id,
            req.work_item_id,
            req.type.value,
            req.status.value,
            req.summary,
            req.detail,
            json.dumps(req.options) if req.options is not None else None,
            req.default,
            req.timeout_hours,
            req.answer,
            req.created_at,
            req.answered_at,
            req.created_by,
        )

    # ── CRUD ─────────────────────────────────────────────────────────

    def create(self, request: Request) -> None:
        cur = self._conn.cursor()
        try:
            cur.execute(
                f"INSERT INTO requests ({self._COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._request_to_params(request),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get(self, request_id: str) -> Request | None:
        row = self._conn.execute(
            f"SELECT {self._COLS} FROM requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_request(row)

    def list_requests(
        self,
        status: RequestStatus | None = None,
        session_id: str | None = None,
        created_by: str | None = None,
        limit: int = 50,
    ) -> list[Request]:
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if created_by is not None:
            conditions.append("created_by = ?")
            params.append(created_by)

        query = f"SELECT {self._COLS} FROM requests"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_request(r) for r in rows]

    # ── mutations ────────────────────────────────────────────────────

    def answer(self, request_id: str, answer: str) -> Request:
        req = self.get(request_id)
        if req is None:
            raise ValueError(f"Request {request_id} not found")
        if req.status != RequestStatus.PENDING:
            raise ValueError(
                f"Cannot answer request {request_id}: status is {req.status.value}, not pending"
            )
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE requests SET status = ?, answer = ?, answered_at = ? WHERE id = ?",
                (RequestStatus.ANSWERED.value, answer, now, request_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get(request_id)  # type: ignore[return-value]

    def reject(self, request_id: str) -> None:
        req = self.get(request_id)
        if req is None:
            raise ValueError(f"Request {request_id} not found")
        if req.status != RequestStatus.PENDING:
            raise ValueError(
                f"Cannot reject request {request_id}: status is {req.status.value}, not pending"
            )
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (RequestStatus.REJECTED.value, request_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def expire(self, request_id: str) -> None:
        req = self.get(request_id)
        if req is None:
            raise ValueError(f"Request {request_id} not found")
        if req.status != RequestStatus.PENDING:
            raise ValueError(
                f"Cannot expire request {request_id}: status is {req.status.value}, not pending"
            )
        cur = self._conn.cursor()
        try:
            updates = "status = ?"
            params: list[Any] = [RequestStatus.EXPIRED.value]
            if req.default is not None:
                updates += ", answer = ?, answered_at = ?"
                params.extend([req.default, self._now()])
            params.append(request_id)
            cur.execute(
                f"UPDATE requests SET {updates} WHERE id = ?",
                params,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def expire_overdue(self) -> int:
        """Expire overdue PREFERENCE requests. Returns count expired."""
        now = datetime.now(timezone.utc)
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM requests "
            "WHERE status = ? AND type = ? AND timeout_hours IS NOT NULL",
            (RequestStatus.PENDING.value, RequestType.PREFERENCE.value),
        ).fetchall()

        count = 0
        for row in rows:
            req = self._row_to_request(row)
            created = datetime.fromisoformat(req.created_at)
            deadline = created + timedelta(hours=req.timeout_hours)
            if now >= deadline:
                self.expire(req.id)
                count += 1
        return count
