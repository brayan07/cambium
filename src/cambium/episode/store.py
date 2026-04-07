"""Episodic memory store — SQLite persistence for episodes and channel events."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from cambium.episode.model import ChannelEvent, Episode, EpisodeStatus


class EpisodeStore:
    """SQLite-backed store for the episodic memory index."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                routine TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                trigger_event_ids TEXT NOT NULL DEFAULT '[]',
                emitted_event_ids TEXT NOT NULL DEFAULT '[]',
                session_acknowledged INTEGER NOT NULL DEFAULT 0,
                session_summary TEXT,
                summarizer_acknowledged INTEGER NOT NULL DEFAULT 0,
                digest_path TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_started
                ON episodes(started_at);
            CREATE INDEX IF NOT EXISTS idx_episodes_routine
                ON episodes(routine, started_at);
            CREATE INDEX IF NOT EXISTS idx_episodes_session
                ON episodes(session_id);

            CREATE TABLE IF NOT EXISTS channel_events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                channel TEXT NOT NULL,
                source_session_id TEXT,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON channel_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_channel
                ON channel_events(channel, timestamp);
        """)

    # --- Episode operations ---

    def create_episode(self, episode: Episode) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodes (id, session_id, routine, started_at, ended_at, "
                "status, trigger_event_ids, emitted_event_ids, session_acknowledged, "
                "session_summary, summarizer_acknowledged, digest_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode.id,
                    episode.session_id,
                    episode.routine,
                    episode.started_at,
                    episode.ended_at,
                    episode.status.value,
                    json.dumps(episode.trigger_event_ids),
                    json.dumps(episode.emitted_event_ids),
                    int(episode.session_acknowledged),
                    episode.session_summary,
                    int(episode.summarizer_acknowledged),
                    episode.digest_path,
                ),
            )
            self._conn.commit()

    def get_episode(self, episode_id: str) -> Episode | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, session_id, routine, started_at, ended_at, status, "
                "trigger_event_ids, emitted_event_ids, session_acknowledged, "
                "session_summary, summarizer_acknowledged, digest_path "
                "FROM episodes WHERE id = ?",
                (episode_id,),
            ).fetchone()
            return self._row_to_episode(row) if row else None

    def get_episode_by_session(self, session_id: str) -> Episode | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, session_id, routine, started_at, ended_at, status, "
                "trigger_event_ids, emitted_event_ids, session_acknowledged, "
                "session_summary, summarizer_acknowledged, digest_path "
                "FROM episodes WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            return self._row_to_episode(row) if row else None

    def complete_episode(self, session_id: str, status: EpisodeStatus) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "UPDATE episodes SET ended_at = ?, status = ? WHERE session_id = ? AND status = 'running'",
                (now, status.value, session_id),
            )
            self._conn.commit()

    def acknowledge_session(self, session_id: str, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE episodes SET session_acknowledged = 1, session_summary = ? "
                "WHERE session_id = ?",
                (summary, session_id),
            )
            self._conn.commit()

    def acknowledge_summarizer(self, session_id: str, digest_path: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE episodes SET summarizer_acknowledged = 1, digest_path = ? "
                "WHERE session_id = ?",
                (digest_path, session_id),
            )
            self._conn.commit()

    def append_emitted_event(self, session_id: str, event_id: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT emitted_event_ids FROM episodes "
                "WHERE session_id = ? AND status = 'running'",
                (session_id,),
            ).fetchone()
            if row is None:
                return
            ids = json.loads(row[0])
            ids.append(event_id)
            self._conn.execute(
                "UPDATE episodes SET emitted_event_ids = ? "
                "WHERE session_id = ? AND status = 'running'",
                (json.dumps(ids), session_id),
            )
            self._conn.commit()

    def list_episodes(
        self,
        since: str,
        until: str,
        routine: str | None = None,
        limit: int = 50,
    ) -> list[Episode]:
        with self._lock:
            query = (
                "SELECT id, session_id, routine, started_at, ended_at, status, "
                "trigger_event_ids, emitted_event_ids, session_acknowledged, "
                "session_summary, summarizer_acknowledged, digest_path "
                "FROM episodes WHERE started_at >= ? AND started_at <= ?"
            )
            params: list = [since, until]

            if routine is not None:
                query += " AND routine = ?"
                params.append(routine)

            query += " ORDER BY started_at DESC, rowid DESC LIMIT ?"
            params.append(limit)

            rows = self._conn.execute(query, params).fetchall()
            return [self._row_to_episode(r) for r in rows]

    def list_unacknowledged(
        self,
        by: str = "session",
        limit: int = 20,
    ) -> list[Episode]:
        if by == "session":
            condition = "session_acknowledged = 0"
        elif by == "summarizer":
            condition = "summarizer_acknowledged = 0"
        else:
            raise ValueError(f"Invalid 'by' value: {by}. Must be 'session' or 'summarizer'.")

        with self._lock:
            query = (
                "SELECT id, session_id, routine, started_at, ended_at, status, "
                "trigger_event_ids, emitted_event_ids, session_acknowledged, "
                "session_summary, summarizer_acknowledged, digest_path "
                f"FROM episodes WHERE {condition} AND status != 'running' "
                "ORDER BY started_at DESC, rowid DESC LIMIT ?"
            )
            rows = self._conn.execute(query, (limit,)).fetchall()
            return [self._row_to_episode(r) for r in rows]

    def _row_to_episode(self, row: tuple) -> Episode:
        return Episode(
            id=row[0],
            session_id=row[1],
            routine=row[2],
            started_at=row[3],
            ended_at=row[4],
            status=EpisodeStatus(row[5]),
            trigger_event_ids=json.loads(row[6]),
            emitted_event_ids=json.loads(row[7]),
            session_acknowledged=bool(row[8]),
            session_summary=row[9],
            summarizer_acknowledged=bool(row[10]),
            digest_path=row[11],
        )

    # --- Channel event operations ---

    def record_event(self, event: ChannelEvent) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO channel_events (id, timestamp, channel, source_session_id, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.timestamp,
                    event.channel,
                    event.source_session_id,
                    json.dumps(event.payload),
                ),
            )
            self._conn.commit()

    def get_event(self, event_id: str) -> ChannelEvent | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, timestamp, channel, source_session_id, payload "
                "FROM channel_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            return self._row_to_event(row) if row else None

    def list_events(
        self,
        since: str | None = None,
        until: str | None = None,
        channel: str | None = None,
        limit: int = 50,
    ) -> list[ChannelEvent]:
        with self._lock:
            query = "SELECT id, timestamp, channel, source_session_id, payload FROM channel_events"
            conditions: list[str] = []
            params: list = []

            if since is not None:
                conditions.append("timestamp >= ?")
                params.append(since)
            if until is not None:
                conditions.append("timestamp <= ?")
                params.append(until)
            if channel is not None:
                conditions.append("channel = ?")
                params.append(channel)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp DESC, rowid DESC LIMIT ?"
            params.append(limit)

            rows = self._conn.execute(query, params).fetchall()
            return [self._row_to_event(r) for r in rows]

    def _row_to_event(self, row: tuple) -> ChannelEvent:
        return ChannelEvent(
            id=row[0],
            timestamp=row[1],
            channel=row[2],
            source_session_id=row[3],
            payload=json.loads(row[4]),
        )
