"""Bootstrap the Cambium user data repository."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml


_DEFAULT_CONFIG = {
    "queue": {
        "adapter": "sqlite",
        "database": "data/cambium.db",
    },
}

_GITIGNORE = "data/\n__pycache__/\n*.pyc\n"

_CONSTITUTION = "# Constitution\n\nDefine your values, goals, and priorities here.\n"


def _get_defaults_dir() -> Path:
    """Locate the defaults/ directory shipped with the framework."""
    return Path(__file__).resolve().parent.parent.parent.parent / "defaults"


def init_user_repo(
    base_path: Path | None = None,
    defaults_dir: Path | None = None,
    github: bool = False,
    repo_name: str = "cambium-config",
) -> Path:
    """Create and populate the ~/.cambium/ directory.

    Copies seed data from the framework's ``defaults/`` directory into the
    user repo. Existing files are never overwritten (the user may have
    customised them).

    Args:
        base_path: Override the default ~/.cambium/ location (useful for testing).
        defaults_dir: Override the defaults source directory (useful for testing).
        github: If True, create a private GitHub repo and set up remote.
        repo_name: GitHub repo name (default: cambium-config).

    Returns:
        The path to the initialised user repo.
    """
    root = base_path or Path.home() / ".cambium"
    root.mkdir(parents=True, exist_ok=True)

    # Ensure core directories exist
    for d in ("data/memory", "data/sessions", "data/logs", "knowledge"):
        (root / d).mkdir(parents=True, exist_ok=True)

    # Write framework files
    _write_if_missing(root / "config.yaml", yaml.dump(_DEFAULT_CONFIG, default_flow_style=False))
    _write_if_missing(root / "constitution.md", _CONSTITUTION)
    _write_if_missing(root / ".gitignore", _GITIGNORE)

    # Copy defaults tree
    defaults = defaults_dir or _get_defaults_dir()
    if defaults.is_dir():
        _copy_defaults(defaults, root)

    # Init git repo if not already one
    is_fresh = not (root / ".git").exists()
    if is_fresh:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-m", "main"], cwd=root, capture_output=True, check=False)

    # Initial commit for fresh repos
    if is_fresh:
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial Cambium configuration"],
            cwd=root, capture_output=True, check=False,
        )

    # Optional GitHub remote
    if github:
        _setup_github(root, repo_name)

    return root


def _copy_defaults(defaults_dir: Path, root: Path) -> None:
    """Walk the defaults tree and copy files into the user repo.

    Existing files are never overwritten. This preserves user customisations
    while seeding new files from framework updates.
    """
    for src_path in defaults_dir.rglob("*"):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(defaults_dir)
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            continue
        # Copy the file
        shutil.copy2(src_path, dest)


def _setup_github(root: Path, repo_name: str) -> None:
    """Create a private GitHub repo and set up remote."""
    if not shutil.which("gh"):
        raise RuntimeError(
            "GitHub CLI (gh) not found. Install it from https://cli.github.com/"
        )

    # Check if origin already exists
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return  # remote already configured

    subprocess.run(
        ["gh", "repo", "create", repo_name, "--private", "--source=.", "--remote=origin"],
        cwd=root, check=True,
    )

    # gh sets an HTTPS remote by default. If the user's git protocol is SSH,
    # rewrite the remote so pushes work without a credential helper.
    proto_result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True,
    )
    if "ssh" in (proto_result.stdout + proto_result.stderr):
        user_result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True,
        )
        gh_user = user_result.stdout.strip()
        if gh_user:
            subprocess.run(
                ["git", "remote", "set-url", "origin", f"git@github.com:{gh_user}/{repo_name}.git"],
                cwd=root, capture_output=True,
            )

    # Push initial commit (best-effort — don't fail init if push fails)
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=root, capture_output=True,
    )


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content)
