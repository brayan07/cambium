"""Budget gate — checks open self-improvement PRs against the configured cap."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

_DEFAULT_MAX_PRS = 3
_LABEL = "self-improvement"


@dataclass
class BudgetCheck:
    """Result of a budget gate check."""

    allowed: bool
    open_prs: int
    max_prs: int
    reason: str = ""


def load_self_improvement_config(config_dir: Path) -> dict[str, Any]:
    """Load self_improvement section from config.yaml."""
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("self_improvement", {})


def check_budget(repo_dir: Path, config_dir: Path | None = None) -> BudgetCheck:
    """Check if we're within the self-improvement PR budget.

    Queries GitHub for open PRs with the 'self-improvement' label.
    Compares against max_pending_improvement_prs from config.

    Args:
        repo_dir: Path to the git repository.
        config_dir: Path to the config directory. If None, uses repo_dir/defaults.
    """
    # Load config
    if config_dir is None:
        from cambium.server.app import _resolve_config_dir
        config_dir = _resolve_config_dir(repo_dir)

    si_config = load_self_improvement_config(config_dir)  # type: ignore[arg-type]
    max_prs = si_config.get("max_pending_improvement_prs", _DEFAULT_MAX_PRS)

    # Check if repo has a GitHub remote
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return BudgetCheck(
                allowed=False, open_prs=0, max_prs=max_prs,
                reason="No GitHub remote configured (run 'cambium init --github')",
            )
    except FileNotFoundError:
        return BudgetCheck(
            allowed=False, open_prs=0, max_prs=max_prs,
            reason="git not found",
        )

    # Query open PRs with self-improvement label
    open_prs = _count_open_prs(repo_dir)
    if open_prs < 0:
        return BudgetCheck(
            allowed=False, open_prs=0, max_prs=max_prs,
            reason="Failed to query GitHub PRs (is 'gh' authenticated?)",
        )

    allowed = open_prs < max_prs
    reason = "" if allowed else (
        f"At PR cap: {open_prs}/{max_prs} self-improvement PRs open"
    )

    return BudgetCheck(
        allowed=allowed, open_prs=open_prs, max_prs=max_prs, reason=reason,
    )


def _count_open_prs(repo_dir: Path) -> int:
    """Count open PRs with the self-improvement label. Returns -1 on error."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--label", _LABEL, "--state", "open", "--json", "number"],
            cwd=str(repo_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.warning(f"gh pr list failed: {result.stderr.strip()}")
            return -1

        import json
        prs = json.loads(result.stdout)
        return len(prs)
    except (FileNotFoundError, Exception) as e:
        log.warning(f"Failed to count PRs: {e}")
        return -1
