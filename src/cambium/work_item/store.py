"""SQLite persistence for work items and their event log."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from datetime import datetime, timezone
from typing import Any

from cambium.work_item.model import (
    VALID_TRANSITIONS,
    CompletionMode,
    RollupMode,
    WorkItem,
    WorkItemEvent,
    WorkItemStatus,
)


class WorkItemStore:
    """Stores work items and an append-only event log in SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS work_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                parent_id TEXT REFERENCES work_items(id),
                priority INTEGER NOT NULL DEFAULT 0,
                completion_mode TEXT NOT NULL DEFAULT 'all',
                rollup_mode TEXT NOT NULL DEFAULT 'auto',
                depends_on TEXT NOT NULL DEFAULT '[]',
                context TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                actor TEXT,
                assigned_to TEXT,
                session_id TEXT,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_work_items_status
                ON work_items(status);
            CREATE INDEX IF NOT EXISTS idx_work_items_parent
                ON work_items(parent_id);

            CREATE TABLE IF NOT EXISTS work_item_events (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES work_items(id),
                event_type TEXT NOT NULL,
                actor TEXT,
                session_id TEXT,
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_work_item_events_item
                ON work_item_events(item_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_work_item_events_type
                ON work_item_events(event_type, created_at);
        """)

    # ── helpers ──────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _emit_event(
        self,
        cursor: sqlite3.Cursor,
        item_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItemEvent:
        event = WorkItemEvent.create(
            item_id=item_id,
            event_type=event_type,
            data=data,
            actor=actor,
            session_id=session_id,
        )
        cursor.execute(
            "INSERT INTO work_item_events "
            "(id, item_id, event_type, actor, session_id, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.item_id,
                event.event_type,
                event.actor,
                event.session_id,
                json.dumps(event.data),
                event.created_at,
            ),
        )
        return event

    def _row_to_item(self, row: tuple) -> WorkItem:
        return WorkItem(
            id=row[0],
            title=row[1],
            description=row[2],
            status=WorkItemStatus(row[3]),
            parent_id=row[4],
            priority=row[5],
            completion_mode=CompletionMode(row[6]),
            rollup_mode=RollupMode(row[7]),
            depends_on=json.loads(row[8]),
            context=json.loads(row[9]),
            result=row[10],
            actor=row[11],
            assigned_to=row[12],
            session_id=row[13],
            max_attempts=row[14],
            attempt_count=row[15],
            reviewed_by=row[16],
            reviewed_at=row[17],
            created_at=row[18],
            updated_at=row[19],
        )

    def _row_to_event(self, row: tuple) -> WorkItemEvent:
        return WorkItemEvent(
            id=row[0],
            item_id=row[1],
            event_type=row[2],
            actor=row[3],
            session_id=row[4],
            data=json.loads(row[5]),
            created_at=row[6],
        )

    _ITEM_COLS = (
        "id, title, description, status, parent_id, priority, "
        "completion_mode, rollup_mode, depends_on, context, result, "
        "actor, assigned_to, session_id, max_attempts, attempt_count, "
        "reviewed_by, reviewed_at, created_at, updated_at"
    )

    _EVENT_COLS = "id, item_id, event_type, actor, session_id, data, created_at"

    # ── CRUD ─────────────────────────────────────────────────────────

    def create(self, item: WorkItem) -> None:
        cur = self._conn.cursor()
        try:
            cur.execute(
                f"INSERT INTO work_items ({self._ITEM_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._item_to_params(item),
            )
            self._emit_event(
                cur,
                item.id,
                "created",
                data={"title": item.title, "parent_id": item.parent_id},
                actor=item.actor,
                session_id=item.session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _item_to_params(self, item: WorkItem) -> tuple:
        return (
            item.id,
            item.title,
            item.description,
            item.status.value,
            item.parent_id,
            item.priority,
            item.completion_mode.value,
            item.rollup_mode.value,
            json.dumps(item.depends_on),
            json.dumps(item.context),
            item.result,
            item.actor,
            item.assigned_to,
            item.session_id,
            item.max_attempts,
            item.attempt_count,
            item.reviewed_by,
            item.reviewed_at,
            item.created_at,
            item.updated_at,
        )

    def get(self, item_id: str) -> WorkItem | None:
        row = self._conn.execute(
            f"SELECT {self._ITEM_COLS} FROM work_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def get_children(self, parent_id: str) -> list[WorkItem]:
        rows = self._conn.execute(
            f"SELECT {self._ITEM_COLS} FROM work_items "
            "WHERE parent_id = ? ORDER BY priority DESC, created_at",
            (parent_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_subtree(self, root_id: str) -> list[WorkItem]:
        """Return all descendants of root_id (not including root) via recursive CTE."""
        rows = self._conn.execute(
            f"""
            WITH RECURSIVE tree AS (
                SELECT {self._ITEM_COLS} FROM work_items WHERE parent_id = ?
                UNION ALL
                SELECT w.{", w.".join(c.strip() for c in self._ITEM_COLS.split(","))}
                FROM work_items w
                JOIN tree t ON w.parent_id = t.id
            )
            SELECT * FROM tree
            """,
            (root_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_dependents(self, item_id: str) -> list[WorkItem]:
        """Find items whose depends_on includes item_id."""
        qualified = ", ".join(
            f"w.{c.strip()}" for c in self._ITEM_COLS.split(",")
        )
        rows = self._conn.execute(
            f"SELECT {qualified} FROM work_items w, json_each(w.depends_on) "
            "WHERE json_each.value = ?",
            (item_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_items(
        self,
        status: WorkItemStatus | None = None,
        parent_id: str | None = None,
        assigned_to: str | None = None,
        limit: int = 200,
    ) -> tuple[list[WorkItem], int]:
        """Return (items, total_count) — total is the untruncated count."""
        where = ""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if parent_id is not None:
            conditions.append("parent_id = ?")
            params.append(parent_id)
        if assigned_to is not None:
            conditions.append("assigned_to = ?")
            params.append(assigned_to)
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        total = self._conn.execute(
            f"SELECT COUNT(*) FROM work_items{where}", params
        ).fetchone()[0]

        rows = self._conn.execute(
            f"SELECT {self._ITEM_COLS} FROM work_items{where}"
            " ORDER BY created_at DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [self._row_to_item(r) for r in rows], total

    def list_ready(self, limit: int = 50) -> list[WorkItem]:
        """List leaf items (no children) with status=ready, ordered by priority DESC."""
        rows = self._conn.execute(
            f"SELECT {self._ITEM_COLS} FROM work_items w "
            "WHERE w.status = 'ready' "
            "AND NOT EXISTS (SELECT 1 FROM work_items c WHERE c.parent_id = w.id) "
            "ORDER BY w.priority DESC, w.created_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    # ── mutations ────────────────────────────────────────────────────

    def update_status(
        self,
        item_id: str,
        new_status: WorkItemStatus,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        item = self.get(item_id)
        if item is None:
            raise ValueError(f"Work item {item_id} not found")

        allowed = VALID_TRANSITIONS.get(item.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {item.status.value} -> {new_status.value}"
            )

        # Failed -> ready only if under max_attempts
        if item.status == WorkItemStatus.FAILED and new_status == WorkItemStatus.READY:
            if item.attempt_count >= item.max_attempts:
                raise ValueError(
                    f"Max attempts ({item.max_attempts}) reached for {item_id}"
                )

        now = self._now()
        cur = self._conn.cursor()
        try:
            updates = "status = ?, updated_at = ?"
            params: list[Any] = [new_status.value, now]

            # Increment attempt_count when transitioning to active
            if new_status == WorkItemStatus.ACTIVE:
                updates += ", attempt_count = attempt_count + 1"

            cur.execute(
                f"UPDATE work_items SET {updates} WHERE id = ?",
                (*params, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "status_changed",
                data={"from": item.status.value, "to": new_status.value},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def claim(
        self,
        item_id: str,
        session_id: str,
        actor: str,
    ) -> WorkItem | None:
        """Atomically claim a ready item. Returns the claimed item or None if race-lost."""
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET status = 'active', actor = ?, session_id = ?, "
                "attempt_count = attempt_count + 1, updated_at = ? "
                "WHERE id = ? AND status = 'ready'",
                (actor, session_id, now, item_id),
            )
            if cur.rowcount == 0:
                self._conn.rollback()
                return None
            self._emit_event(
                cur,
                item_id,
                "claimed",
                data={"actor": actor, "session_id": session_id},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
            return self.get(item_id)
        except Exception:
            self._conn.rollback()
            raise

    def set_result(
        self,
        item_id: str,
        result: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET result = ?, updated_at = ? WHERE id = ?",
                (result, now, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "result_set",
                data={"result": result},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def set_reviewed(
        self,
        item_id: str,
        reviewed_by: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Mark an item as reviewed."""
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET reviewed_by = ?, reviewed_at = ?, updated_at = ? "
                "WHERE id = ?",
                (reviewed_by, now, now, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "reviewed",
                data={"reviewed_by": reviewed_by, "verdict": "accepted"},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_context(
        self,
        item_id: str,
        context: dict[str, Any],
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Merge keys into existing context."""
        item = self.get(item_id)
        if item is None:
            return
        merged = {**item.context, **context}
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET context = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged), now, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "context_updated",
                data={"merged_keys": list(context.keys())},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def add_dependency(
        self,
        item_id: str,
        dependency_id: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Add a dependency, checking for cycles via BFS."""
        item = self.get(item_id)
        if item is None:
            raise ValueError(f"Work item {item_id} not found")
        if dependency_id in item.depends_on:
            return  # already present

        # Cycle detection: BFS from dependency_id through depends_on chains
        if self._would_create_cycle(item_id, dependency_id):
            raise ValueError(
                f"Adding dependency {dependency_id} to {item_id} would create a cycle"
            )

        new_deps = item.depends_on + [dependency_id]
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET depends_on = ?, updated_at = ? WHERE id = ?",
                (json.dumps(new_deps), now, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "dependency_added",
                data={"dependency_id": dependency_id},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _would_create_cycle(self, item_id: str, new_dep_id: str) -> bool:
        """Check if adding new_dep_id as a dependency of item_id would create a cycle."""
        # If item_id is reachable from new_dep_id via depends_on, it's a cycle
        visited: set[str] = set()
        queue: deque[str] = deque([new_dep_id])
        while queue:
            current = queue.popleft()
            if current == item_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            dep_item = self.get(current)
            if dep_item:
                for dep in dep_item.depends_on:
                    if dep not in visited:
                        queue.append(dep)
        return False

    def remove_dependency(
        self,
        item_id: str,
        dependency_id: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        item = self.get(item_id)
        if item is None:
            raise ValueError(f"Work item {item_id} not found")
        if dependency_id not in item.depends_on:
            return
        new_deps = [d for d in item.depends_on if d != dependency_id]
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET depends_on = ?, updated_at = ? WHERE id = ?",
                (json.dumps(new_deps), now, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "dependency_removed",
                data={"dependency_id": dependency_id},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def reparent(
        self,
        item_id: str,
        new_parent_id: str | None,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        item = self.get(item_id)
        if item is None:
            raise ValueError(f"Work item {item_id} not found")
        old_parent_id = item.parent_id
        now = self._now()
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE work_items SET parent_id = ?, updated_at = ? WHERE id = ?",
                (new_parent_id, now, item_id),
            )
            self._emit_event(
                cur,
                item_id,
                "reparented",
                data={"from_parent": old_parent_id, "to_parent": new_parent_id},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def create_children(
        self,
        parent_id: str,
        children: list[WorkItem],
        actor: str | None = None,
        session_id: str | None = None,
    ) -> list[WorkItem]:
        """Batch-create children under a parent in one transaction."""
        parent = self.get(parent_id)
        if parent is None:
            raise ValueError(f"Parent work item {parent_id} not found")

        cur = self._conn.cursor()
        try:
            for child in children:
                child.parent_id = parent_id
                cur.execute(
                    f"INSERT INTO work_items ({self._ITEM_COLS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._item_to_params(child),
                )
                self._emit_event(
                    cur,
                    child.id,
                    "created",
                    data={"title": child.title, "parent_id": parent_id},
                    actor=actor,
                    session_id=session_id,
                )
            self._emit_event(
                cur,
                parent_id,
                "children_created",
                data={"child_ids": [c.id for c in children]},
                actor=actor,
                session_id=session_id,
            )
            self._conn.commit()
            return children
        except Exception:
            self._conn.rollback()
            raise

    # ── event log ────────────────────────────────────────────────────

    def get_events(
        self,
        item_id: str | None = None,
        event_type: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[WorkItemEvent]:
        query = f"SELECT {self._EVENT_COLS} FROM work_item_events"
        conditions: list[str] = []
        params: list[Any] = []
        if item_id is not None:
            conditions.append("item_id = ?")
            params.append(item_id)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if after is not None:
            conditions.append("created_at > ?")
            params.append(after)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_event(r) for r in rows]
