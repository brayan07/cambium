"""Routine data model and registry.

A routine binds channel subscriptions to an adapter instance.
It defines the event wiring — what to listen for and what it's allowed to publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Routine:
    """A routine is a YAML-defined channel handler that references an adapter instance."""

    name: str
    adapter_instance: str
    listen: list[str] = field(default_factory=list)
    publish: list[str] = field(default_factory=list)
    suppress_completion_event: bool = False
    max_concurrency: int = 0  # 0 = unbounded
    batch_window: float = 0.0  # seconds; 0 = no batching
    batch_max: int = 1  # max messages per batch; 1 = no batching

    @classmethod
    def from_file(cls, path: Path) -> Routine:
        data = yaml.safe_load(path.read_text()) or {}
        return cls(
            name=data.get("name", path.stem),
            adapter_instance=data.get("adapter_instance", ""),
            listen=data.get("listen", []),
            publish=data.get("publish", []),
            suppress_completion_event=data.get("suppress_completion_event", False),
            max_concurrency=data.get("max_concurrency", 0),
            batch_window=float(data.get("batch_window", 0)),
            batch_max=int(data.get("batch_max", 1)),
        )


class RoutineRegistry:
    """Loads routines from directories. Later directories override earlier ones."""

    def __init__(self, *directories: Path) -> None:
        self._routines: dict[str, Routine] = {}
        for d in directories:
            if d.is_dir():
                for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
                    routine = Routine.from_file(f)
                    self._routines[routine.name] = routine

    def get(self, name: str) -> Routine | None:
        return self._routines.get(name)

    def all(self) -> list[Routine]:
        return list(self._routines.values())

    def for_channel(self, channel: str) -> list[Routine]:
        """Return all routines listening on a given channel."""
        return [r for r in self._routines.values() if channel in r.listen]

    def subscribed_channels(self) -> list[str]:
        """Return all channels that at least one routine listens on."""
        channels: set[str] = set()
        for r in self._routines.values():
            channels.update(r.listen)
        return sorted(channels)
