"""Skill runner — builds and executes LLM sessions."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from cambium.models.event import Event
from cambium.models.routine import Routine
from cambium.models.skill import SkillRegistry

log = logging.getLogger(__name__)


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

    def execute(self, config: SessionConfig, live: bool = True, timeout: int = 1200) -> SessionResult:
        """Execute a session via claude -p.

        Args:
            config: The assembled session configuration.
            live: If True, use real claude -p execution. If False, return mock.
            timeout: Max seconds before killing the subprocess.
        """
        if not live:
            return self._mock_execute(config)
        return self._live_execute(config, timeout)

    def _mock_execute(self, config: SessionConfig) -> SessionResult:
        """Return a mock result for testing."""
        return SessionResult(
            success=True,
            output=f"[mock] Executed routine '{config.routine_name}' for event '{config.event.type}'",
            events_emitted=[],
            duration_seconds=0.0,
        )

    def _live_execute(self, config: SessionConfig, timeout: int) -> SessionResult:
        """Execute via claude -p subprocess."""
        start = time.monotonic()

        # Build the user message from event payload
        user_msg = json.dumps(config.event.payload, indent=2) if config.event.payload else config.event.type

        # Build claude command
        cmd = [
            "claude", "-p", user_msg,
            "--model", "opus",
            "--output-format", "stream-json",
            "--verbose",
        ]

        # Add system prompt
        if config.prompt:
            cmd.extend(["--system-prompt", config.prompt])

        # Add allowed tools
        for tool in config.tools:
            cmd.extend(["--allowedTools", tool])

        cwd = config.working_directory or None

        log.info(f"Executing routine '{config.routine_name}' for event '{config.event.type}'")
        log.debug(f"Command: {' '.join(cmd[:6])}... ({len(config.prompt)} char prompt, {len(config.tools)} tools)")

        try:
            # Wrap with script for pseudo-TTY (same fix as async-runner)
            wrapped_cmd = ["script", "-q", "/dev/null"] + cmd

            proc = subprocess.run(
                wrapped_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            duration = time.monotonic() - start
            output = proc.stdout or ""

            # Parse stream-json output for the final result
            result_text = self._extract_result(output)

            if proc.returncode == 0:
                return SessionResult(
                    success=True,
                    output=result_text,
                    events_emitted=[],
                    duration_seconds=duration,
                )
            else:
                return SessionResult(
                    success=False,
                    output=result_text,
                    events_emitted=[],
                    duration_seconds=duration,
                    error=proc.stderr[:500] if proc.stderr else f"Exit code {proc.returncode}",
                )

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return SessionResult(
                success=False,
                output="",
                events_emitted=[],
                duration_seconds=duration,
                error=f"Timed out after {timeout}s",
            )
        except FileNotFoundError:
            duration = time.monotonic() - start
            return SessionResult(
                success=False,
                output="",
                events_emitted=[],
                duration_seconds=duration,
                error="claude CLI not found — is it installed and on PATH?",
            )

    @staticmethod
    def _extract_result(stream_output: str) -> str:
        """Extract the final assistant message from stream-json output."""
        last_text = ""
        for line in stream_output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "result":
                    last_text = msg.get("result", last_text)
                elif msg.get("type") == "assistant" and "message" in msg:
                    # Accumulate text content
                    content = msg["message"].get("content", [])
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_text = block.get("text", last_text)
            except json.JSONDecodeError:
                continue
        return last_text
