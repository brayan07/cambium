"""SQLite persistence for preference dimensions, signals, cases, and objectives."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from cambium.preference.model import (
    Dimension,
    DimensionState,
    ObjectiveDefinition,
    ObjectiveReport,
    PreferenceCase,
    Signal,
)


class PreferenceStore:
    """Stores preference state, signal history, case library, and objectives in SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS dimensions (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                anchors TEXT NOT NULL DEFAULT '{}',
                constitutional_source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS preference_state (
                dimension_id TEXT NOT NULL REFERENCES dimensions(id),
                context_key TEXT NOT NULL DEFAULT 'global',
                mean REAL NOT NULL,
                variance REAL NOT NULL,
                update_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (dimension_id, context_key)
            );

            CREATE INDEX IF NOT EXISTS idx_pref_state_dim
                ON preference_state(dimension_id);

            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                dimension_id TEXT NOT NULL REFERENCES dimensions(id),
                context_key TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_value REAL NOT NULL,
                observation_variance REAL NOT NULL,
                prior_mean REAL NOT NULL,
                prior_variance REAL NOT NULL,
                posterior_mean REAL NOT NULL,
                posterior_variance REAL NOT NULL,
                source_item_id TEXT,
                raw_data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_signals_dim_ctx
                ON signals(dimension_id, context_key, created_at);
            CREATE INDEX IF NOT EXISTS idx_signals_source
                ON signals(source_item_id);

            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT '',
                task_type TEXT NOT NULL DEFAULT '',
                goal_areas TEXT NOT NULL DEFAULT '[]',
                priority INTEGER NOT NULL DEFAULT 0,
                action_summary TEXT NOT NULL,
                outcome TEXT NOT NULL,
                feedback TEXT,
                lesson TEXT NOT NULL,
                dimensions_affected TEXT NOT NULL DEFAULT '[]',
                signal_direction REAL NOT NULL DEFAULT 0,
                retrieval_count INTEGER NOT NULL DEFAULT 0,
                usefulness_score REAL NOT NULL DEFAULT 0.5,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_retrieved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_cases_domain
                ON cases(domain, task_type, archived);
            CREATE INDEX IF NOT EXISTS idx_cases_item
                ON cases(work_item_id);

            CREATE TABLE IF NOT EXISTS objective_definitions (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                constitutional_goal TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scale_min REAL NOT NULL DEFAULT 1.0,
                scale_max REAL NOT NULL DEFAULT 5.0,
                cadence TEXT NOT NULL DEFAULT 'weekly',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS objective_reports (
                id TEXT PRIMARY KEY,
                objective_id TEXT NOT NULL REFERENCES objective_definitions(id),
                value REAL NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_obj_reports_obj
                ON objective_reports(objective_id, created_at);

            CREATE TABLE IF NOT EXISTS interruption_budget (
                date TEXT PRIMARY KEY,
                max_questions INTEGER NOT NULL DEFAULT 5,
                questions_asked INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
        """)

    # ── helpers ──────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Dimensions ──────────────────────────────────────────────────

    def create_dimension(self, dim: Dimension) -> None:
        self._conn.execute(
            "INSERT INTO dimensions (id, name, description, anchors, constitutional_source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dim.id, dim.name, dim.description, json.dumps(dim.anchors),
             dim.constitutional_source, dim.created_at, dim.updated_at),
        )
        self._conn.commit()

    def get_dimension(self, dim_id: str) -> Dimension | None:
        row = self._conn.execute(
            "SELECT id, name, description, anchors, constitutional_source, created_at, updated_at "
            "FROM dimensions WHERE id = ?", (dim_id,),
        ).fetchone()
        return self._row_to_dimension(row) if row else None

    def get_dimension_by_name(self, name: str) -> Dimension | None:
        row = self._conn.execute(
            "SELECT id, name, description, anchors, constitutional_source, created_at, updated_at "
            "FROM dimensions WHERE name = ?", (name,),
        ).fetchone()
        return self._row_to_dimension(row) if row else None

    def list_dimensions(self) -> list[Dimension]:
        rows = self._conn.execute(
            "SELECT id, name, description, anchors, constitutional_source, created_at, updated_at "
            "FROM dimensions ORDER BY name",
        ).fetchall()
        return [self._row_to_dimension(r) for r in rows]

    def _row_to_dimension(self, row: tuple) -> Dimension:
        return Dimension(
            id=row[0], name=row[1], description=row[2],
            anchors=json.loads(row[3]), constitutional_source=row[4],
            created_at=row[5], updated_at=row[6],
        )

    # ── Preference state ────────────────────────────────────────────

    def get_state(self, dimension_id: str, context_key: str = "global") -> DimensionState | None:
        row = self._conn.execute(
            "SELECT dimension_id, context_key, mean, variance, update_count, created_at, updated_at "
            "FROM preference_state WHERE dimension_id = ? AND context_key = ?",
            (dimension_id, context_key),
        ).fetchone()
        return self._row_to_state(row) if row else None

    def resolve_state(self, dimension_id: str, context_keys: list[str]) -> DimensionState | None:
        """Try each context key in order, return first match."""
        for key in context_keys:
            state = self.get_state(dimension_id, key)
            if state is not None:
                return state
        return None

    def set_state(
        self, dimension_id: str, context_key: str, mean: float, variance: float,
    ) -> None:
        now = self._now()
        self._conn.execute(
            "INSERT INTO preference_state (dimension_id, context_key, mean, variance, update_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?) "
            "ON CONFLICT(dimension_id, context_key) DO UPDATE SET mean=?, variance=?, updated_at=?",
            (dimension_id, context_key, mean, variance, now, now, mean, variance, now),
        )
        self._conn.commit()

    def update_posterior(
        self,
        dimension_id: str,
        context_key: str,
        observation: float,
        obs_variance: float,
        source_item_id: str | None = None,
        signal_type: str = "unknown",
        raw_data: dict[str, Any] | None = None,
    ) -> Signal:
        """Conjugate Gaussian update. Records signal with before/after snapshots."""
        state = self.get_state(dimension_id, context_key)
        if state is None:
            # Fall back to global, or create with wide prior
            state = self.get_state(dimension_id, "global")
        if state is None:
            raise ValueError(f"No state for dimension {dimension_id} in any context")

        prior_mean = state.mean
        prior_var = state.variance

        # Bayesian conjugate update
        new_var = 1.0 / (1.0 / prior_var + 1.0 / obs_variance)
        new_mean = new_var * (prior_mean / prior_var + observation / obs_variance)

        # Update state
        now = self._now()
        self._conn.execute(
            "INSERT INTO preference_state (dimension_id, context_key, mean, variance, update_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(dimension_id, context_key) DO UPDATE SET "
            "mean=?, variance=?, update_count=update_count+1, updated_at=?",
            (dimension_id, context_key, new_mean, new_var, now, now,
             new_mean, new_var, now),
        )

        # Record signal
        signal = Signal.create(
            dimension_id=dimension_id,
            context_key=context_key,
            signal_type=signal_type,
            signal_value=observation,
            observation_variance=obs_variance,
            prior_mean=prior_mean,
            prior_variance=prior_var,
            posterior_mean=new_mean,
            posterior_variance=new_var,
            source_item_id=source_item_id,
            raw_data=raw_data,
        )
        self._conn.execute(
            "INSERT INTO signals (id, dimension_id, context_key, signal_type, signal_value, "
            "observation_variance, prior_mean, prior_variance, posterior_mean, posterior_variance, "
            "source_item_id, raw_data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (signal.id, signal.dimension_id, signal.context_key, signal.signal_type,
             signal.signal_value, signal.observation_variance,
             signal.prior_mean, signal.prior_variance,
             signal.posterior_mean, signal.posterior_variance,
             signal.source_item_id, json.dumps(signal.raw_data), signal.created_at),
        )
        self._conn.commit()
        return signal

    def _row_to_state(self, row: tuple) -> DimensionState:
        return DimensionState(
            dimension_id=row[0], context_key=row[1],
            mean=row[2], variance=row[3], update_count=row[4],
            created_at=row[5], updated_at=row[6],
        )

    # ── Signals ─────────────────────────────────────────────────────

    def get_signals(
        self,
        dimension_id: str | None = None,
        context_key: str | None = None,
        source_item_id: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        query = "SELECT id, dimension_id, context_key, signal_type, signal_value, " \
                "observation_variance, prior_mean, prior_variance, posterior_mean, " \
                "posterior_variance, source_item_id, raw_data, created_at FROM signals WHERE 1=1"
        params: list[Any] = []

        if dimension_id is not None:
            query += " AND dimension_id = ?"
            params.append(dimension_id)
        if context_key is not None:
            query += " AND context_key = ?"
            params.append(context_key)
        if source_item_id is not None:
            query += " AND source_item_id = ?"
            params.append(source_item_id)
        if after is not None:
            query += " AND created_at > ?"
            params.append(after)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def _row_to_signal(self, row: tuple) -> Signal:
        return Signal(
            id=row[0], dimension_id=row[1], context_key=row[2],
            signal_type=row[3], signal_value=row[4], observation_variance=row[5],
            prior_mean=row[6], prior_variance=row[7],
            posterior_mean=row[8], posterior_variance=row[9],
            source_item_id=row[10], raw_data=json.loads(row[11]),
            created_at=row[12],
        )

    # ── Cases ───────────────────────────────────────────────────────

    def create_case(self, case: PreferenceCase) -> None:
        self._conn.execute(
            "INSERT INTO cases (id, work_item_id, domain, task_type, goal_areas, priority, "
            "action_summary, outcome, feedback, lesson, dimensions_affected, signal_direction, "
            "retrieval_count, usefulness_score, archived, created_at, last_retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case.id, case.work_item_id, case.domain, case.task_type,
             json.dumps(case.goal_areas), case.priority,
             case.action_summary, case.outcome, case.feedback, case.lesson,
             json.dumps(case.dimensions_affected), case.signal_direction,
             case.retrieval_count, case.usefulness_score, int(case.archived),
             case.created_at, case.last_retrieved_at),
        )
        self._conn.commit()

    def get_case(self, case_id: str) -> PreferenceCase | None:
        row = self._conn.execute(
            "SELECT id, work_item_id, domain, task_type, goal_areas, priority, "
            "action_summary, outcome, feedback, lesson, dimensions_affected, signal_direction, "
            "retrieval_count, usefulness_score, archived, created_at, last_retrieved_at "
            "FROM cases WHERE id = ?", (case_id,),
        ).fetchone()
        return self._row_to_case(row) if row else None

    def query_cases(
        self,
        domain: str | None = None,
        task_type: str | None = None,
        archived: bool = False,
        limit: int = 20,
    ) -> list[PreferenceCase]:
        query = "SELECT id, work_item_id, domain, task_type, goal_areas, priority, " \
                "action_summary, outcome, feedback, lesson, dimensions_affected, signal_direction, " \
                "retrieval_count, usefulness_score, archived, created_at, last_retrieved_at " \
                "FROM cases WHERE archived = ?"
        params: list[Any] = [int(archived)]

        if domain is not None:
            query += " AND domain = ?"
            params.append(domain)
        if task_type is not None:
            query += " AND task_type = ?"
            params.append(task_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_case(r) for r in rows]

    def update_case_retrieval(self, case_id: str) -> None:
        now = self._now()
        self._conn.execute(
            "UPDATE cases SET retrieval_count = retrieval_count + 1, last_retrieved_at = ? WHERE id = ?",
            (now, case_id),
        )
        self._conn.commit()

    def update_case_usefulness(self, case_id: str, delta: float) -> None:
        self._conn.execute(
            "UPDATE cases SET usefulness_score = MAX(0.0, MIN(1.0, usefulness_score + ?)) WHERE id = ?",
            (delta, case_id),
        )
        self._conn.commit()

    def archive_case(self, case_id: str) -> None:
        self._conn.execute("UPDATE cases SET archived = 1 WHERE id = ?", (case_id,))
        self._conn.commit()

    def _row_to_case(self, row: tuple) -> PreferenceCase:
        return PreferenceCase(
            id=row[0], work_item_id=row[1], domain=row[2], task_type=row[3],
            goal_areas=json.loads(row[4]), priority=row[5],
            action_summary=row[6], outcome=row[7], feedback=row[8], lesson=row[9],
            dimensions_affected=json.loads(row[10]), signal_direction=row[11],
            retrieval_count=row[12], usefulness_score=row[13], archived=bool(row[14]),
            created_at=row[15], last_retrieved_at=row[16],
        )

    # ── Objectives ──────────────────────────────────────────────────

    def create_objective(self, obj: ObjectiveDefinition) -> None:
        self._conn.execute(
            "INSERT INTO objective_definitions (id, name, constitutional_goal, description, "
            "scale_min, scale_max, cadence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (obj.id, obj.name, obj.constitutional_goal, obj.description,
             obj.scale_min, obj.scale_max, obj.cadence, obj.created_at),
        )
        self._conn.commit()

    def get_objective_by_name(self, name: str) -> ObjectiveDefinition | None:
        row = self._conn.execute(
            "SELECT id, name, constitutional_goal, description, scale_min, scale_max, cadence, created_at "
            "FROM objective_definitions WHERE name = ?", (name,),
        ).fetchone()
        if row is None:
            return None
        return ObjectiveDefinition(
            id=row[0], name=row[1], constitutional_goal=row[2], description=row[3],
            scale_min=row[4], scale_max=row[5], cadence=row[6], created_at=row[7],
        )

    def list_objectives(self) -> list[ObjectiveDefinition]:
        rows = self._conn.execute(
            "SELECT id, name, constitutional_goal, description, scale_min, scale_max, cadence, created_at "
            "FROM objective_definitions ORDER BY name",
        ).fetchall()
        return [ObjectiveDefinition(
            id=r[0], name=r[1], constitutional_goal=r[2], description=r[3],
            scale_min=r[4], scale_max=r[5], cadence=r[6], created_at=r[7],
        ) for r in rows]

    def record_objective_report(self, report: ObjectiveReport) -> None:
        self._conn.execute(
            "INSERT INTO objective_reports (id, objective_id, value, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (report.id, report.objective_id, report.value, report.notes, report.created_at),
        )
        self._conn.commit()

    def get_objective_reports(
        self,
        objective_id: str,
        after: str | None = None,
        limit: int = 50,
    ) -> list[ObjectiveReport]:
        query = "SELECT id, objective_id, value, notes, created_at FROM objective_reports WHERE objective_id = ?"
        params: list[Any] = [objective_id]
        if after:
            query += " AND created_at > ?"
            params.append(after)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [ObjectiveReport(id=r[0], objective_id=r[1], value=r[2], notes=r[3], created_at=r[4])
                for r in rows]

    # ── Interruption budget ─────────────────────────────────────────

    def get_budget_today(self) -> tuple[int, int]:
        """Returns (max_questions, questions_asked) for today."""
        today = self._today()
        row = self._conn.execute(
            "SELECT max_questions, questions_asked FROM interruption_budget WHERE date = ?",
            (today,),
        ).fetchone()
        if row is None:
            return 5, 0
        return row[0], row[1]

    def increment_budget(self) -> None:
        today = self._today()
        now = self._now()
        self._conn.execute(
            "INSERT INTO interruption_budget (date, max_questions, questions_asked, updated_at) "
            "VALUES (?, 5, 1, ?) "
            "ON CONFLICT(date) DO UPDATE SET questions_asked = questions_asked + 1, updated_at = ?",
            (today, now, now),
        )
        self._conn.commit()

    def reset_budget(self, max_questions: int = 5) -> None:
        today = self._today()
        now = self._now()
        self._conn.execute(
            "INSERT INTO interruption_budget (date, max_questions, questions_asked, updated_at) "
            "VALUES (?, ?, 0, ?) "
            "ON CONFLICT(date) DO UPDATE SET max_questions = ?, questions_asked = 0, updated_at = ?",
            (today, max_questions, now, max_questions, now),
        )
        self._conn.commit()
