"""Claude Code adapter type.

Translates adapter instance config into `claude -p` CLI execution.
Manages the Claude Code capability library (skills, sub-agents).
Translates stream-json output into OpenAI chat.completion.chunk format.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from cambium.adapters.base import AdapterInstance, AdapterType, RunResult
from cambium.mcp.registry import MCPRegistry
from cambium.models.skill import SkillRegistry
from cambium.session.model import TranscriptEvent

log = logging.getLogger(__name__)


class ClaudeCodeAdapter(AdapterType):
    """Adapter type for Claude Code CLI."""

    name = "claude-code"

    def __init__(
        self,
        skill_registry: SkillRegistry,
        user_dir: Path | None = None,
        mcp_registry: MCPRegistry | None = None,
    ) -> None:
        self.skill_registry = skill_registry
        self.user_dir = user_dir
        self.mcp_registry = mcp_registry

    def send_message(
        self,
        instance: AdapterInstance,
        user_message: str,
        session_id: str,
        session_token: str = "",
        api_base_url: str = "",
        live: bool = True,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_raw_event: Callable[[TranscriptEvent], None] | None = None,
        cwd: Path | None = None,
        resume: bool = False,
    ) -> RunResult:
        if not live:
            return self._mock_send(instance, user_message, session_id, on_event)
        return self._live_send(
            instance, user_message, session_id, session_token, api_base_url,
            on_event, on_raw_event, cwd, resume,
        )

    def _mock_send(
        self,
        instance: AdapterInstance,
        user_message: str,
        session_id: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> RunResult:
        text = f"[mock] {instance.name}: {user_message[:80]}"
        if on_event:
            on_event(_make_text_chunk(session_id, instance.config.get("model", "mock"), text))
            on_event(_make_done_chunk(session_id, instance.config.get("model", "mock")))
        return RunResult(success=True, output=text, duration_seconds=0.0, session_id=session_id)

    def _live_send(
        self,
        instance: AdapterInstance,
        user_message: str,
        session_id: str,
        session_token: str,
        api_base_url: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_raw_event: Callable[[TranscriptEvent], None] | None = None,
        cwd: Path | None = None,
        resume: bool = False,
    ) -> RunResult:
        start = time.monotonic()
        tmp_dir = None
        config = instance.config

        try:
            skill_names = config.get("skills", [])
            tmp_dir = self._build_skills_dir(skill_names)

            # Resolve MCP servers into cwd — Claude discovers .mcp.json from the
            # project root (cwd), not from --add-dir.
            mcp_cwd = None
            if not cwd:
                # Create a temp working dir so we have somewhere to write .mcp.json
                mcp_cwd = Path(tempfile.mkdtemp(prefix="cambium-mcp-"))
                cwd = mcp_cwd
            mcp_config_path = self._resolve_mcp_servers(config, cwd)

            system_prompt = self._load_system_prompt(config)
            prompt_file = Path(tmp_dir) / "system-prompt.md"
            prompt_file.write_text(system_prompt)

            model = config.get("model", "opus")
            timeout = config.get("timeout", 1200)

            cmd = [
                "claude",
                "--print", "-",
                "--output-format", "stream-json",
                "--verbose",
                "--model", model,
                "--dangerously-skip-permissions",
                "--add-dir", tmp_dir,
                "--append-system-prompt-file", str(prompt_file),
            ]

            if resume:
                cmd.extend(["--resume", session_id])
            else:
                cmd.extend(["--session-id", session_id])

            env = os.environ.copy()
            env["CAMBIUM_TOKEN"] = session_token
            env["CAMBIUM_API_URL"] = api_base_url

            log.info(
                f"{'Resuming' if resume else 'Starting'} session '{session_id[:8]}' "
                f"instance='{instance.name}' model={model} skills={len(skill_names)}"
            )

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=cwd,
            )

            assert proc.stdin is not None
            proc.stdin.write(user_message)
            proc.stdin.close()

            last_text = ""
            chunk_id = f"chatcmpl-{session_id[:12]}"

            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                parsed = _parse_stream_line(line)
                if not parsed:
                    continue

                # Translate to TranscriptEvent and emit for persistence
                # Skip "result" events — they duplicate the final assistant message
                if on_raw_event and parsed.get("type") != "result":
                    on_raw_event(_to_transcript_event(parsed))

                # Translate to OpenAI chunks and emit
                chunks = _stream_json_to_openai(parsed, chunk_id, model)
                for chunk in chunks:
                    if on_event:
                        on_event(chunk)

                # Track final text for RunResult
                if parsed.get("type") == "result":
                    last_text = parsed.get("result", last_text)
                elif parsed.get("type") == "assistant" and "message" in parsed:
                    for block in parsed["message"].get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_text = block.get("text", last_text)

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                if on_event:
                    on_event(_make_done_chunk(chunk_id, model))
                return RunResult(
                    success=False,
                    output=last_text,
                    duration_seconds=time.monotonic() - start,
                    error=f"Timed out after {timeout}s",
                    session_id=session_id,
                )

            duration = time.monotonic() - start
            stderr_text = proc.stderr.read() if proc.stderr else ""

            # Emit done chunk
            if on_event:
                on_event(_make_done_chunk(chunk_id, model))

            if proc.returncode == 0:
                return RunResult(
                    success=True,
                    output=last_text,
                    duration_seconds=duration,
                    session_id=session_id,
                )
            else:
                return RunResult(
                    success=False,
                    output=last_text,
                    duration_seconds=duration,
                    error=stderr_text[:500] if stderr_text else f"Exit code {proc.returncode}",
                    session_id=session_id,
                )

        except FileNotFoundError:
            return RunResult(
                success=False,
                output="",
                duration_seconds=time.monotonic() - start,
                error="claude CLI not found — is it installed and on PATH?",
            )
        finally:
            if tmp_dir and os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            if mcp_cwd and mcp_cwd.exists():
                shutil.rmtree(mcp_cwd, ignore_errors=True)
            elif mcp_config_path and mcp_config_path.exists():
                # Clean up .mcp.json from caller-provided cwd
                mcp_config_path.unlink(missing_ok=True)

    def _resolve_mcp_servers(self, config: dict, target_dir: Path) -> Path | None:
        """Resolve named MCP servers and write .mcp.json into target_dir.

        Reads ``mcp_servers`` from the instance config, looks each up in the
        MCP registry, and writes a Claude Code compatible ``.mcp.json``.
        Returns the path written, or None if no servers were resolved.
        """
        mcp_names = config.get("mcp_servers", [])
        if not mcp_names or not self.mcp_registry:
            return None

        mcp_json: dict[str, dict] = {}
        for name in mcp_names:
            server = self.mcp_registry.get(name)
            if server is None:
                log.warning(f"MCP server '{name}' not found in registry — skipping")
                continue
            mcp_json[name] = server.to_mcp_json()

        if mcp_json:
            config_path = target_dir / ".mcp.json"
            config_path.write_text(json.dumps({"mcpServers": mcp_json}, indent=2))
            log.info(f"Wrote .mcp.json with {len(mcp_json)} server(s): {list(mcp_json)}")
            return config_path
        return None

    def _build_skills_dir(self, skill_names: list[str]) -> str:
        """Create ephemeral directory with .claude/skills/ symlinks."""
        tmp_dir = tempfile.mkdtemp(prefix="cambium-skills-")
        skills_target = Path(tmp_dir) / ".claude" / "skills"
        skills_target.mkdir(parents=True)

        for name in skill_names:
            skill = self.skill_registry.get(name)
            if skill is None:
                continue
            (skills_target / name).symlink_to(skill.dir_path)

        return tmp_dir

    def _load_system_prompt(self, config: dict) -> str:
        """Load system prompt from the path specified in config.

        Paths are resolved relative to user_dir if not absolute.
        """
        prompt_path = config.get("system_prompt_path", "")
        if not prompt_path:
            return ""
        path = Path(prompt_path)
        if not path.is_absolute() and self.user_dir:
            path = self.user_dir / path
        if path.exists():
            return path.read_text()
        return ""

    def attach(
        self, instance: AdapterInstance, session_id: str, cwd: Path | None = None,
    ) -> None:
        """Attach to a Claude Code session.

        Builds the skills directory and system prompt, then execs into
        the ``claude`` CLI. This replaces the current process.
        """
        import atexit

        config = instance.config
        skill_names = config.get("skills", [])
        tmp_dir = self._build_skills_dir(skill_names)
        atexit.register(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        # Resolve MCP servers into cwd — Claude discovers .mcp.json from the
        # project root (cwd), not from --add-dir.
        if cwd:
            mcp_config_path = self._resolve_mcp_servers(config, cwd)
            if mcp_config_path:
                atexit.register(lambda p=mcp_config_path: p.unlink(missing_ok=True))

        system_prompt = self._load_system_prompt(config)
        prompt_file = Path(tmp_dir) / "system-prompt.md"
        prompt_file.write_text(system_prompt)

        model = config.get("model", "opus")

        cmd = [
            "claude",
            "--session-id", session_id,
            "--model", model,
            "--dangerously-skip-permissions",
            "--add-dir", tmp_dir,
            "--append-system-prompt-file", str(prompt_file),
        ]

        log.info(
            f"Attaching to session '{session_id[:8]}' "
            f"instance='{instance.name}' model={model}"
        )

        if cwd:
            os.chdir(cwd)
        os.execvp("claude", cmd)


# --- Stream-JSON to OpenAI translation ---


def _parse_stream_line(line: str) -> dict | None:
    """Parse a single line of stream-json output."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _make_text_chunk(chunk_id: str, model: str, text: str) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


def _make_done_chunk(chunk_id: str, model: str) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }


def _stream_json_to_openai(
    event: dict, chunk_id: str, model: str
) -> list[dict[str, Any]]:
    """Translate a Claude Code stream-json event to OpenAI chunk(s).

    Returns a list because some events map to zero or multiple chunks.
    """
    chunks: list[dict[str, Any]] = []
    event_type = event.get("type")

    if event_type == "assistant" and "message" in event:
        for block in event["message"].get("content", []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    chunks.append(_make_text_chunk(chunk_id, model, text))

            elif block_type == "thinking":
                text = block.get("thinking", "")
                if text:
                    chunk = _make_text_chunk(chunk_id, model, text)
                    chunk["choices"][0]["thinking"] = True
                    chunks.append(chunk)

            elif block_type == "tool_use":
                tool_chunk: dict[str, Any] = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": block.get("id", ""),
                                        "type": "function",
                                        "function": {
                                            "name": block.get("name", ""),
                                            "arguments": json.dumps(
                                                block.get("input", {})
                                            ),
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                chunks.append(tool_chunk)

            elif block_type == "tool_result":
                result_chunk: dict[str, Any] = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                    "tool_result": {
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": block.get("content", ""),
                    },
                }
                chunks.append(result_chunk)

    # result events are NOT translated to chunks — they duplicate the
    # final assistant text. They're only used for RunResult.output.

    return chunks


# --- Stream-JSON to TranscriptEvent translation ---

_ROLE_MAP = {
    "assistant": "assistant",
    "result": "assistant",
    "system": "system",
    "user": "user",
}


def _to_transcript_event(event: dict) -> TranscriptEvent:
    """Translate a Claude Code stream-json event into an adapter-agnostic TranscriptEvent.

    This is the only place that knows about Claude Code's event format.
    The runner persists TranscriptEvents without inspecting their contents.
    """
    event_type = event.get("type", "unknown")
    role = _ROLE_MAP.get(event_type, event_type)
    content = _extract_content(event, event_type)
    return TranscriptEvent(role=role, content=content, event_type=event_type, raw=event)


def _extract_content(event: dict, event_type: str) -> str:
    """Extract human-readable content from a Claude Code stream-json event."""
    if event_type == "assistant" and "message" in event:
        parts = []
        for block in event["message"].get("content", []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                parts.append(block.get("text", ""))
            elif block_type == "thinking":
                parts.append(f"[thinking] {block.get('thinking', '')}")
            elif block_type == "tool_use":
                parts.append(
                    f"[tool_use] {block.get('name', '?')}"
                    f"({json.dumps(block.get('input', {}))})"
                )
            elif block_type == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    result_content = " ".join(
                        b.get("text", "") for b in result_content if isinstance(b, dict)
                    )
                parts.append(f"[tool_result] {result_content}")
        return "\n".join(parts) if parts else json.dumps(event)

    if event_type == "user" and "message" in event:
        # Tool results come back as user messages with content blocks
        parts = []
        for block in event["message"].get("content", []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    result_content = " ".join(
                        b.get("text", "") for b in result_content if isinstance(b, dict)
                    )
                parts.append(f"[tool_result:{block.get('tool_use_id', '?')}] {result_content}")
            else:
                parts.append(json.dumps(block))
        return "\n".join(parts) if parts else json.dumps(event)

    if event_type == "result":
        return event.get("result", "")

    if event_type == "system":
        subtype = event.get("subtype", "")
        return f"[system:{subtype}]" if subtype else "[system]"

    if event_type == "rate_limit_event":
        info = event.get("rate_limit_info", {})
        return f"[rate_limit] status={info.get('status', '?')} resets_at={info.get('resetsAt', '?')}"

    # Catch-all: preserve full event as JSON so nothing is lost
    return json.dumps(event)
