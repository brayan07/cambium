"""MCPRegistry backed by a local JSON file in the user directory.

Reads server definitions from a JSON file (default
``~/.cambium/mcp-servers.json``). The format is compatible with mcpm
and Claude Code's .mcp.json — if you ever want to switch backends,
the data migrates trivially.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from cambium.mcp.registry import MCPRegistry, MCPServerConfig

log = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".cambium" / "mcp-servers.json"


class FileRegistry:
    """Read-only MCP registry backed by a single JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH

    def get(self, name: str) -> MCPServerConfig | None:
        return self._load().get(name)

    def list_all(self) -> dict[str, MCPServerConfig]:
        return self._load()

    def _load(self) -> dict[str, MCPServerConfig]:
        if not self._path.exists():
            log.debug(f"MCP server config not found at {self._path}")
            return {}

        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read MCP server config: {e}")
            return {}

        servers: dict[str, MCPServerConfig] = {}
        for name, entry in raw.items():
            try:
                servers[name] = _parse_entry(name, entry)
            except (KeyError, TypeError) as e:
                log.warning(f"Skipping malformed MCP entry '{name}': {e}")
        return servers


def _parse_entry(name: str, entry: dict) -> MCPServerConfig:
    """Translate a JSON server entry to MCPServerConfig."""
    if "command" in entry:
        return MCPServerConfig(
            name=name,
            command=entry["command"],
            args=entry.get("args", []),
            env=entry.get("env", {}),
        )
    elif "url" in entry:
        return MCPServerConfig(
            name=name,
            url=entry["url"],
            headers=entry.get("headers", {}),
        )
    raise KeyError(f"Cannot determine transport type for '{name}' — need 'command' or 'url'")


# Type-check: FileRegistry satisfies the MCPRegistry protocol
_: type[MCPRegistry] = FileRegistry  # type: ignore[assignment]
