"""Adapter type abstraction.

An adapter type implements a specific runtime (Claude Code, Codex, local model).
An adapter instance is a user-built configuration of an adapter type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from cambium.session.model import TranscriptEvent


@dataclass
class RunResult:
    """Outcome of an adapter instance execution."""

    success: bool
    output: str
    duration_seconds: float = 0.0
    error: str | None = None
    session_id: str | None = None


@dataclass
class AdapterInstance:
    """A named configuration of an adapter type. Config blob is opaque to the framework."""

    name: str
    adapter_type: str
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> AdapterInstance:
        data = yaml.safe_load(path.read_text()) or {}
        return cls(
            name=data.get("name", path.stem),
            adapter_type=data.get("adapter_type", ""),
            config=data.get("config", {}),
        )


class AdapterInstanceRegistry:
    """Loads adapter instances from directories."""

    def __init__(self, *directories: Path) -> None:
        self._instances: dict[str, AdapterInstance] = {}
        for d in directories:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
                instance = AdapterInstance.from_file(f)
                self._instances[instance.name] = instance

    def get(self, name: str) -> AdapterInstance | None:
        return self._instances.get(name)

    def all(self) -> list[AdapterInstance]:
        return list(self._instances.values())


class AdapterType(ABC):
    """Base class for runtime adapters. Each adapter type knows how to execute its instances."""

    name: str

    @abstractmethod
    def send_message(
        self,
        instance: AdapterInstance,
        user_message: str,
        session_id: str,
        session_token: str = "",
        api_base_url: str = "",
        images: list[str] | None = None,
        live: bool = True,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_raw_event: Callable[[TranscriptEvent], None] | None = None,
        cwd: Path | None = None,
        resume: bool = False,
    ) -> RunResult:
        """Send a message in a session context.

        Args:
            instance: The adapter instance configuration.
            user_message: The user's message text.
            session_id: Cambium session ID.
            session_token: JWT for authenticating with the Cambium API.
            api_base_url: Base URL of the Cambium API server.
            live: If False, return a mock result (for testing).
            on_event: Callback receiving OpenAI chat.completion.chunk dicts.
            on_raw_event: Callback receiving TranscriptEvents for persistence.
                Each adapter translates its native events into TranscriptEvent.
            resume: If True, the session has prior conversation history and the
                adapter should continue it rather than starting fresh.
        """
        ...

    def attach(
        self,
        instance: AdapterInstance,
        session_id: str,
        cwd: Path | None = None,
        resume: bool = False,
    ) -> None:
        """Attach to a live session.

        Typically execs into the adapter's CLI (e.g. claude, codex).
        This replaces the current process — it does not return.

        Raises NotImplementedError if the adapter doesn't support attach mode.
        """
        raise NotImplementedError(
            f"Adapter type '{self.name}' does not support attach"
        )
