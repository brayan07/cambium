"""SQLite persistence for metric readings."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from cambium.metric.model import Reading

log = logging.getLogger(__name__)


class ReadingStore:
    """Stores metric readings and survey→request associations in SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                id TEXT PRIMARY KEY,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_readings_metric_time
                ON readings(metric_name, recorded_at);

            CREATE TABLE IF NOT EXISTS survey_requests (
                request_id TEXT PRIMARY KEY,
                metric_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

    # ── helpers ──────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    _READING_COLS = "id, metric_name, value, detail, source, recorded_at"

    def _row_to_reading(self, row: tuple) -> Reading:
        return Reading(
            id=row[0],
            metric_name=row[1],
            value=row[2],
            detail=row[3],
            source=row[4],
            recorded_at=row[5],
        )

    # ── reading CRUD ─────────────────────────────────────────────────

    def record_reading(self, reading: Reading) -> Reading:
        cur = self._conn.cursor()
        try:
            cur.execute(
                f"INSERT INTO readings ({self._READING_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    reading.id,
                    reading.metric_name,
                    reading.value,
                    reading.detail,
                    reading.source,
                    reading.recorded_at,
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return reading

    def list_readings(
        self,
        metric_name: str,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[Reading]:
        conditions = ["metric_name = ?"]
        params: list = [metric_name]
        if since is not None:
            conditions.append("recorded_at >= ?")
            params.append(since)
        if until is not None:
            conditions.append("recorded_at <= ?")
            params.append(until)

        query = (
            f"SELECT {self._READING_COLS} FROM readings "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY recorded_at DESC LIMIT ?"
        )
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_reading(r) for r in rows]

    def get_latest_reading(self, metric_name: str) -> Reading | None:
        row = self._conn.execute(
            f"SELECT {self._READING_COLS} FROM readings "
            "WHERE metric_name = ? ORDER BY recorded_at DESC LIMIT 1",
            (metric_name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_reading(row)

    def get_summary(
        self,
        metric_name: str,
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        """Aggregate stats: min, max, avg, count, latest value."""
        conditions = ["metric_name = ?"]
        params: list = [metric_name]
        if since is not None:
            conditions.append("recorded_at >= ?")
            params.append(since)
        if until is not None:
            conditions.append("recorded_at <= ?")
            params.append(until)

        where = " AND ".join(conditions)
        row = self._conn.execute(
            f"SELECT MIN(value), MAX(value), AVG(value), COUNT(*) "
            f"FROM readings WHERE {where}",
            params,
        ).fetchone()

        latest = self.get_latest_reading(metric_name)

        return {
            "metric_name": metric_name,
            "min": row[0],
            "max": row[1],
            "avg": row[2],
            "count": row[3],
            "latest_value": latest.value if latest else None,
            "latest_at": latest.recorded_at if latest else None,
        }

    def get_orphaned_metric_names(self, known_names: set[str]) -> list[str]:
        """Return metric names in readings table that aren't in the known config set."""
        rows = self._conn.execute(
            "SELECT DISTINCT metric_name FROM readings"
        ).fetchall()
        return [r[0] for r in rows if r[0] not in known_names]

    # ── survey request tracking ──────────────────────────────────────

    def link_survey_request(self, request_id: str, metric_name: str) -> None:
        cur = self._conn.cursor()
        try:
            cur.execute(
                "INSERT INTO survey_requests (request_id, metric_name, created_at) "
                "VALUES (?, ?, ?)",
                (request_id, metric_name, self._now()),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_metric_for_request(self, request_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT metric_name FROM survey_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return row[0] if row else None

    def has_reading_for_source(self, source: str) -> bool:
        """Check if a reading already exists with this source (dedup guard)."""
        row = self._conn.execute(
            "SELECT 1 FROM readings WHERE source = ? LIMIT 1",
            (source,),
        ).fetchone()
        return row is not None
