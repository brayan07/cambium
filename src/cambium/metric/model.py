"""Metric model — YAML-defined metric configs and time-series readings."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


class MetricType(str, Enum):
    DETERMINISTIC = "deterministic"
    INTELLIGENT = "intelligent"
    SURVEY = "survey"


@dataclass
class MetricConfig:
    """Base class — common fields for all metric types. Loaded from YAML."""

    name: str
    type: MetricType
    description: str
    unit: str
    tags: list[str]
    schedule: str  # cron expression


@dataclass
class DeterministicMetric(MetricConfig):
    script_path: str = ""  # relative to config_dir


@dataclass
class SurveyMetric(MetricConfig):
    survey_summary: str = ""
    survey_options: list[str] = field(default_factory=list)
    survey_detail: str = ""


@dataclass
class IntelligentMetric(MetricConfig):
    instance: str = "metric-analyst"


_TYPE_MAP: dict[MetricType, type[MetricConfig]] = {
    MetricType.DETERMINISTIC: DeterministicMetric,
    MetricType.SURVEY: SurveyMetric,
    MetricType.INTELLIGENT: IntelligentMetric,
}


@dataclass
class Reading:
    id: str
    metric_name: str
    value: float
    detail: str
    source: str
    recorded_at: str

    @classmethod
    def create(
        cls,
        metric_name: str,
        value: float,
        detail: str = "",
        source: str = "system",
    ) -> Reading:
        return cls(
            id=str(uuid.uuid4()),
            metric_name=metric_name,
            value=value,
            detail=detail,
            source=source,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )


def _parse_metric(raw: dict) -> MetricConfig:
    """Parse a single metric entry from YAML into the appropriate subclass."""
    metric_type = MetricType(raw["type"])
    cls = _TYPE_MAP[metric_type]

    name = raw["name"]
    description = raw.get("description", "")
    unit = raw.get("unit", "")
    tags: list[str] = raw.get("tags", [])
    schedule = raw["schedule"]

    if cls is DeterministicMetric:
        return DeterministicMetric(
            name=name, type=metric_type, description=description,
            unit=unit, tags=tags, schedule=schedule,
            script_path=raw.get("script_path", ""),
        )
    elif cls is SurveyMetric:
        return SurveyMetric(
            name=name, type=metric_type, description=description,
            unit=unit, tags=tags, schedule=schedule,
            survey_summary=raw.get("survey_summary", ""),
            survey_options=raw.get("survey_options", []),
            survey_detail=raw.get("survey_detail", ""),
        )
    elif cls is IntelligentMetric:
        return IntelligentMetric(
            name=name, type=metric_type, description=description,
            unit=unit, tags=tags, schedule=schedule,
            instance=raw.get("instance", "metric-analyst"),
        )
    else:
        return MetricConfig(
            name=name, type=metric_type, description=description,
            unit=unit, tags=tags, schedule=schedule,
        )


def load_metrics(path: Path) -> list[MetricConfig]:
    """Load metric configs from a YAML file. Returns empty list if file doesn't exist."""
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text()) or {}
    metrics_raw = data.get("metrics", [])

    results: list[MetricConfig] = []
    for raw in metrics_raw:
        try:
            results.append(_parse_metric(raw))
        except (KeyError, ValueError) as exc:
            log.warning("Skipping invalid metric config %r: %s", raw.get("name", "?"), exc)

    names = [m.name for m in results]
    if len(names) != len(set(names)):
        dupes = [n for n in names if names.count(n) > 1]
        log.warning("Duplicate metric names in %s: %s", path, set(dupes))

    return results
