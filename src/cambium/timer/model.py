"""Timer configuration model — cron-scheduled message publishing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TimerConfig:
    """A timer publishes a message to a channel on a cron schedule."""

    name: str
    channel: str
    schedule: str  # cron expression (e.g., "*/5 * * * *")
    payload: dict = field(default_factory=dict)


def load_timers(path: Path) -> list[TimerConfig]:
    """Load timer configs from a YAML file. Returns empty list if file doesn't exist."""
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text()) or {}
    timers = data.get("timers", [])

    return [
        TimerConfig(
            name=t["name"],
            channel=t["channel"],
            schedule=t["schedule"],
            payload=t.get("payload", {}),
        )
        for t in timers
    ]
