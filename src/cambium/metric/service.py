"""Business logic for metrics — reading recording and metric config access."""

from __future__ import annotations

import logging

from cambium.metric.model import MetricConfig, Reading
from cambium.metric.store import ReadingStore
from cambium.models.message import Message
from cambium.queue.base import QueueAdapter

log = logging.getLogger(__name__)


class MetricService:
    """Wraps ReadingStore with channel publishing and config access."""

    def __init__(
        self,
        store: ReadingStore,
        queue: QueueAdapter,
        metrics: list[MetricConfig],
    ) -> None:
        self.store = store
        self.queue = queue
        self._metrics = {m.name: m for m in metrics}

    def get_metrics(
        self,
        type: str | None = None,
        tag: str | None = None,
    ) -> list[MetricConfig]:
        results = list(self._metrics.values())
        if type is not None:
            results = [m for m in results if m.type.value == type]
        if tag is not None:
            results = [m for m in results if tag in m.tags]
        return results

    def get_metric(self, name: str) -> MetricConfig | None:
        return self._metrics.get(name)

    def record_reading(
        self,
        metric_name: str,
        value: float,
        detail: str = "",
        source: str = "system",
    ) -> Reading:
        if metric_name not in self._metrics:
            raise ValueError(f"Unknown metric: {metric_name}")

        reading = Reading.create(
            metric_name=metric_name,
            value=value,
            detail=detail,
            source=source,
        )
        self.store.record_reading(reading)

        self.queue.publish(Message.create(
            channel="metric_readings",
            payload={
                "metric_name": metric_name,
                "value": value,
                "source": source,
            },
            source="metric-service",
        ))

        log.info("Recorded reading for %s: %.4f", metric_name, value)
        return reading

    def list_readings(
        self,
        metric_name: str,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[Reading]:
        if metric_name not in self._metrics:
            raise ValueError(f"Unknown metric: {metric_name}")
        return self.store.list_readings(metric_name, since=since, until=until, limit=limit)

    def get_summary(
        self,
        metric_name: str,
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        if metric_name not in self._metrics:
            raise ValueError(f"Unknown metric: {metric_name}")
        return self.store.get_summary(metric_name, since=since, until=until)
