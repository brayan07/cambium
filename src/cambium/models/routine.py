"""Routine data model and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Routine:
    """A routine is a YAML-defined event handler that binds skills to event types."""

    name: str
    prompt_path: str
    skills: list[str] = field(default_factory=list)
    subscribe: list[str] = field(default_factory=list)
    emit: list[str] = field(default_factory=list)
    persistent: bool = False
    session_key: str | None = None
    working_directory: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> Routine:
        """Parse a routine from a YAML file."""
        data = yaml.safe_load(path.read_text()) or {}
        return cls(
            name=data.get("name", path.stem),
            prompt_path=data.get("prompt_path", ""),
            skills=data.get("skills", []),
            subscribe=data.get("subscribe", []),
            emit=data.get("emit", []),
            persistent=data.get("persistent", False),
            session_key=data.get("session_key"),
            working_directory=data.get("working_directory"),
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
        """Get a routine by name."""
        return self._routines.get(name)

    def all(self) -> list[Routine]:
        """Return all loaded routines."""
        return list(self._routines.values())

    def for_event_type(self, event_type: str) -> list[Routine]:
        """Return all routines that subscribe to a given event type."""
        return [r for r in self._routines.values() if event_type in r.subscribe]

    def subscribed_event_types(self) -> list[str]:
        """Return all event types that at least one routine subscribes to."""
        types: set[str] = set()
        for r in self._routines.values():
            types.update(r.subscribe)
        return sorted(types)
