"""MCP registry protocol and server config model.

This module defines the interface that any MCP backend must implement.
The adapter layer depends only on this protocol — never on a concrete backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MCPServerConfig:
    """Transport-agnostic MCP server definition."""

    name: str

    # stdio transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # remote transport (SSE / streamable-http)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_stdio(self) -> bool:
        return self.command is not None

    @property
    def is_remote(self) -> bool:
        return self.url is not None

    def to_mcp_json(self) -> dict:
        """Serialize to Claude Code .mcp.json entry format."""
        if self.is_stdio:
            entry: dict = {"command": self.command, "args": self.args}
            if self.env:
                entry["env"] = self.env
            return entry
        elif self.is_remote:
            entry = {"url": self.url}
            if self.headers:
                entry["headers"] = self.headers
            return entry
        raise ValueError(f"Server '{self.name}' has neither command nor url")


@runtime_checkable
class MCPRegistry(Protocol):
    """Interface for resolving MCP server names to configurations.

    Implementations may read from mcpm, ToolHive, a local JSON file, etc.
    The adapter layer calls only these two methods.
    """

    def get(self, name: str) -> MCPServerConfig | None:
        """Look up a single server by name. Returns None if not found."""
        ...

    def list_all(self) -> dict[str, MCPServerConfig]:
        """Return all registered servers keyed by name."""
        ...
