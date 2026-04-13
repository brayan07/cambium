"""MetricRunner — pure Python metric scheduler and executor.

Handles all three metric types:
- Deterministic: executes bash scripts, records readings
- Survey: fires SURVEY requests, processes answered responses
- Intelligent: publishes to metric_collect channel for LLM analyst routines
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter

from cambium.metric.model import (
    DeterministicMetric,
    IntelligentMetric,
    MetricConfig,
    Reading,
    SurveyMetric,
)
from cambium.metric.store import ReadingStore
from cambium.models.message import Message
from cambium.queue.base import QueueAdapter
from cambium.request.model import RequestStatus, RequestType
from cambium.request.service import RequestService

log = logging.getLogger(__name__)


class MetricRunner:
    """Schedules all metrics. Executes deterministic + survey in Python.
    Dispatches intelligent metrics to analyst routines via channel."""

    def __init__(
        self,
        metrics: list[MetricConfig],
        store: ReadingStore,
        request_service: RequestService,
        queue: QueueAdapter,
        config_dir: Path,
        api_base_url: str = "http://localhost:8000",
    ) -> None:
        self.metrics = {m.name: m for m in metrics}
        self.store = store
        self.request_service = request_service
        self.queue = queue
        self.config_dir = config_dir
        self.api_base_url = api_base_url

    def tick(self) -> None:
        """Called on each heartbeat. Checks schedules and dispatches work."""
        now = datetime.now(timezone.utc)
        self._run_due_deterministic(now)
        self._fire_due_surveys(now)
        self._process_answered_surveys()
        self._dispatch_due_intelligent(now)

    # ── deterministic ────────────────────────────────────────────────

    def _run_due_deterministic(self, now: datetime) -> None:
        for m in self.metrics.values():
            if not isinstance(m, DeterministicMetric):
                continue
            if not self._is_due(m.name, m.schedule, now):
                continue
            try:
                result = self._execute_script(m)
                reading = Reading.create(
                    metric_name=m.name,
                    value=result["value"],
                    detail=result.get("detail", ""),
                    source="script",
                )
                self.store.record_reading(reading)
                log.info("Recorded deterministic reading for %s: %.4f", m.name, reading.value)
            except Exception:
                log.exception("Failed to execute deterministic metric %s", m.name)

    def _execute_script(self, metric: DeterministicMetric) -> dict:
        script = self.config_dir / metric.script_path
        if not script.exists():
            raise FileNotFoundError(f"Metric script not found: {script}")

        env = {**os.environ, "CAMBIUM_API_URL": self.api_base_url}
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Metric script {metric.script_path} exited {result.returncode}: "
                f"{result.stderr[:500]}"
            )
        return json.loads(result.stdout.strip())

    # ── survey ───────────────────────────────────────────────────────

    def _fire_due_surveys(self, now: datetime) -> None:
        for m in self.metrics.values():
            if not isinstance(m, SurveyMetric):
                continue
            if not self._is_survey_due(m.name, m.schedule, now):
                continue
            try:
                request = self.request_service.create_request(
                    session_id=None,
                    type=RequestType.SURVEY,
                    summary=m.survey_summary,
                    detail=m.survey_detail,
                    options=m.survey_options,
                    created_by="metric-runner",
                )
                self.store.link_survey_request(request.id, m.name)
                log.info("Fired survey for metric %s (request %s)", m.name, request.id[:8])
            except Exception:
                log.exception("Failed to fire survey for metric %s", m.name)

    def _process_answered_surveys(self) -> None:
        answered = self.request_service.store.list_requests(
            status=RequestStatus.ANSWERED,
            type=RequestType.SURVEY,
        )

        for req in answered:
            metric_name = self.store.get_metric_for_request(req.id)
            if metric_name is None:
                continue
            source = f"survey:{req.id}"
            if self.store.has_reading_for_source(source):
                continue
            try:
                value = float(req.answer)
            except (TypeError, ValueError):
                log.warning(
                    "Survey response for metric %s is not numeric: %r",
                    metric_name, req.answer,
                )
                continue
            reading = Reading.create(
                metric_name=metric_name,
                value=value,
                detail="User survey response",
                source=source,
            )
            self.store.record_reading(reading)
            log.info("Recorded survey reading for %s: %.1f", metric_name, value)

    # ── intelligent ──────────────────────────────────────────────────

    def _dispatch_due_intelligent(self, now: datetime) -> None:
        by_instance: dict[str, list[str]] = {}
        for m in self.metrics.values():
            if not isinstance(m, IntelligentMetric):
                continue
            if not self._is_due(m.name, m.schedule, now):
                continue
            by_instance.setdefault(m.instance, []).append(m.name)

        for instance, metric_names in by_instance.items():
            self.queue.publish(Message.create(
                channel="metric_collect",
                payload={"target": instance, "metrics": metric_names},
                source="metric-runner",
            ))
            log.info(
                "Dispatched %d intelligent metric(s) to %s: %s",
                len(metric_names), instance, metric_names,
            )

    # ── scheduling ───────────────────────────────────────────────────

    def _is_due(self, metric_name: str, cron_expr: str, now: datetime) -> bool:
        if not cron_expr:
            return False
        last = self.store.get_latest_reading(metric_name)
        if last is None:
            return True  # never run — due immediately
        last_time = datetime.fromisoformat(last.recorded_at)
        cron = croniter(cron_expr, last_time)
        next_fire = cron.get_next(datetime)
        return now >= next_fire

    def _is_survey_due(self, metric_name: str, cron_expr: str, now: datetime) -> bool:
        """Survey scheduling is anchored on the last *fire* time, not the
        last reading. Surveys only produce a reading when the user
        answers, so using readings here re-fires every tick while the
        survey is pending. We look at survey_requests instead."""
        if not cron_expr:
            return False
        last_fired = self.store.get_latest_survey_fired_at(metric_name)
        if last_fired is None:
            return True
        last_time = datetime.fromisoformat(last_fired)
        cron = croniter(cron_expr, last_time)
        next_fire = cron.get_next(datetime)
        return now >= next_fire
