"""Memory service — initializes the long-term memory directory and manages consolidator state.

The memory directory is a standalone local git repo. Routines read and write
markdown files directly via the filesystem. This service only handles:
1. Directory structure + git repo initialization
2. Consolidator checkpoint state (read/write)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Seed content for initial directory setup
_MASTER_INDEX = """\
# Memory

This is the system's long-term memory. It is maintained by Cambium routines
and versioned with git.

## Sections

- [Sessions](sessions/) — digests of routine invocations, partitioned by date
- [Digests](digests/) — periodic rollups (daily, weekly, monthly)
- [Knowledge](knowledge/) — the system's beliefs, organized by domain
- [Library](library/) — digested external content (books, papers, courses)
"""

_KNOWLEDGE_INDEX = """\
# Knowledge

The system's beliefs — claims it treats as true for decision-making.

Each entry has a confidence score (0–1), evidence trail, and last-confirmed date.
New domains are created as the system learns.

## Domains

- [User](user/) — understanding of the user
"""

_USER_INDEX = """\
# User

The system's understanding of the user — preferences, working patterns, goals, context.
"""

_LIBRARY_INDEX = """\
# Library

Digested external content — books, papers, courses. Reference material, not
endorsed as truth. The system may cite library entries but should not treat
them as established beliefs without independent verification.
"""

_CONSOLIDATOR_STATE = """\
---
last_session_processed: null
last_daily_digest: null
last_weekly_digest: null
last_hourly_scan: null
---
"""


class MemoryService:
    """Minimal service for memory directory initialization and consolidator state."""

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._ensure_initialized()

    @property
    def path(self) -> Path:
        """Return the memory directory path."""
        return self._memory_dir

    def get_consolidator_state(self) -> dict:
        """Parse .consolidator-state.md frontmatter and return as dict."""
        state_file = self._memory_dir / ".consolidator-state.md"
        if not state_file.exists():
            return {}
        return self._parse_frontmatter(state_file.read_text())

    def update_consolidator_state(self, updates: dict) -> None:
        """Merge updates into .consolidator-state.md frontmatter and git commit."""
        state = self.get_consolidator_state()
        state.update(updates)

        state_file = self._memory_dir / ".consolidator-state.md"
        content = "---\n" + yaml.dump(state, default_flow_style=False) + "---\n"
        state_file.write_text(content)

        self._git_commit("Update consolidator state", [str(state_file)])

    def _ensure_initialized(self) -> None:
        """Create directory structure, seed files, and git repo if not present."""
        dirs = [
            self._memory_dir,
            self._memory_dir / "sessions",
            self._memory_dir / "digests" / "daily",
            self._memory_dir / "digests" / "weekly",
            self._memory_dir / "digests" / "monthly",
            self._memory_dir / "knowledge" / "user",
            self._memory_dir / "library",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Write seed files only if they don't exist
        seeds = {
            self._memory_dir / "_index.md": _MASTER_INDEX,
            self._memory_dir / "knowledge" / "_index.md": _KNOWLEDGE_INDEX,
            self._memory_dir / "knowledge" / "user" / "_index.md": _USER_INDEX,
            self._memory_dir / "library" / "_index.md": _LIBRARY_INDEX,
            self._memory_dir / ".consolidator-state.md": _CONSOLIDATOR_STATE,
        }
        for path, content in seeds.items():
            if not path.exists():
                path.write_text(content)

        # Initialize git repo
        git_dir = self._memory_dir / ".git"
        if not git_dir.exists():
            self._run_git("init")
            self._run_git("add", ".")
            self._run_git("commit", "-m", "Initialize memory directory")
            log.info(f"Initialized memory repo at {self._memory_dir}")

    def _git_commit(self, message: str, paths: list[str]) -> None:
        """Stage specific files and commit."""
        for p in paths:
            self._run_git("add", p)
        # Only commit if there are staged changes
        result = self._run_git("diff", "--cached", "--quiet", check=False)
        if result.returncode != 0:
            self._run_git("commit", "-m", message)

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self._memory_dir,
            capture_output=True,
            text=True,
            check=check,
        )

    @staticmethod
    def _parse_frontmatter(text: str) -> dict:
        """Extract YAML frontmatter from a markdown file."""
        if not text.startswith("---"):
            return {}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}
