"""Skill runner — builds and executes LLM sessions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from cambium.models.event import Event
from cambium.models.routine import Routine
from cambium.models.skill import SkillRegistry


@dataclass
class SessionConfig:
    """Everything needed to execute a single LLM session."""

    prompt: str
    tools: list[str]
    event: Event
    routine_name: str
    working_directory: str | None = None
    session_key: str | None = None


@dataclass
class SessionResult:
    """Outcome of a session execution."""

    success: bool
    output: str
    events_emitted: list[Event] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str | None = None


class SkillRunner:
    """Resolves skills and builds sessions for routine execution."""

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self.skill_registry = skill_registry

    def build_session(self, routine: Routine, event: Event, prompt_base_dir: Path | None = None) -> SessionConfig:
        """Resolve skills, assemble prompt, return a SessionConfig ready for execution.

        Args:
            routine: The routine definition.
            event: The triggering event.
            prompt_base_dir: Base directory for resolving relative prompt_path. If None, prompt_path is used as-is.
        """
        # Resolve and load skill contents
        skill_contents: list[str] = []
        tools: list[str] = []
        missing: list[str] = []

        for skill_name in routine.skills:
            skill = self.skill_registry.get(skill_name)
            if skill is None:
                missing.append(skill_name)
                continue
            skill_contents.append(f"## Skill: {skill.name}\n\n{skill.content}")
            tools.extend(t for t in skill.tools if t not in tools)

        if missing:
            raise ValueError(f"Missing skills: {', '.join(missing)}")

        # Load routine prompt
        prompt_text = ""
        if routine.prompt_path:
            if prompt_base_dir:
                prompt_file = prompt_base_dir / routine.prompt_path
            else:
                prompt_file = Path(routine.prompt_path)
            if prompt_file.exists():
                prompt_text = prompt_file.read_text()

        # Assemble full prompt
        parts = []
        if prompt_text:
            parts.append(prompt_text)
        if skill_contents:
            parts.append("\n\n---\n\n".join(skill_contents))
        full_prompt = "\n\n---\n\n".join(parts) if parts else ""

        return SessionConfig(
            prompt=full_prompt,
            tools=tools,
            event=event,
            routine_name=routine.name,
            working_directory=routine.working_directory,
            session_key=routine.session_key,
        )

    def execute(self, config: SessionConfig) -> SessionResult:
        """Execute a session. MVP: returns a mock result."""
        start = time.monotonic()
        # MVP mock execution — real implementation calls claude -p
        duration = time.monotonic() - start
        return SessionResult(
            success=True,
            output=f"[mock] Executed routine '{config.routine_name}' for event '{config.event.type}'",
            events_emitted=[],
            duration_seconds=duration,
        )
