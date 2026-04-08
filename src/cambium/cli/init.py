"""Bootstrap the Cambium user repository (combined code + config)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import yaml


log = logging.getLogger(__name__)

# Patterns excluded when copying the framework repo to the user's directory.
_COPY_EXCLUDE = shutil.ignore_patterns(
    ".git", ".venv", "node_modules", "__pycache__",
    "*.pyc", "*.db", ".pytest_cache", ".DS_Store",
    "*.egg-info", "dist", ".idea",
)

_GITIGNORE = """\
__pycache__/
*.py[cod]
*$py.class
.venv/
*.egg-info/
dist/
.pytest_cache/
*.db
.DS_Store
.idea/
node_modules/
"""

def _get_constitution_template() -> str:
    """Read the constitution template from defaults, with a fallback stub."""
    template = _get_defaults_dir() / "constitution-template.md"
    if template.exists():
        return template.read_text()
    return "# Constitution\n\nDefine your values, goals, and priorities here.\n"

_DATA_DIRS = ("memory", "sessions", "logs")


def _get_framework_dir() -> Path:
    """Locate the framework repository root (parent of src/)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _get_defaults_dir() -> Path:
    """Locate the defaults/ directory shipped with the framework."""
    return _get_framework_dir() / "defaults"


def _get_framework_version() -> str:
    """Get the current framework git commit hash."""
    framework_dir = _get_framework_dir()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(framework_dir),
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return "unknown"


def init_user_repo(
    base_path: Path | None = None,
    defaults_dir: Path | None = None,
    github: bool = False,
    repo_name: str = "cambium-config",
    data_dir: Path | None = None,
    framework_dir: Path | None = None,
) -> Path:
    """Create and populate a Cambium user repository.

    In combined-repo mode (default), copies the entire framework into the
    user's directory. In legacy mode (when defaults_dir is provided), only
    copies defaults/ — this preserves backward compatibility with existing
    tests and the config-only workflow.

    Args:
        base_path: Target directory for the user repo (default: ~/cambium/).
        defaults_dir: Override defaults source (legacy mode — copies defaults only).
        github: If True, create a private GitHub repo and set up remote.
        repo_name: GitHub repo name (default: cambium-config).
        data_dir: Runtime state directory (default: ~/.cambium/).
        framework_dir: Override framework source for full-repo copy.

    Returns:
        The path to the initialised user repo.
    """
    root = base_path or Path.home() / "cambium"
    root.mkdir(parents=True, exist_ok=True)

    # Choose copy mode: full repo or defaults-only
    if defaults_dir is not None:
        # Legacy mode — just copy defaults into root
        _init_legacy(root, defaults_dir)
    else:
        # Combined repo mode — copy entire framework
        fw_dir = framework_dir or _get_framework_dir()
        _init_combined(root, fw_dir)

    # Ensure data directory exists (runtime state, separate from repo)
    _ensure_data_dir(data_dir or Path.home() / ".cambium")

    # Init git repo if not already one
    is_fresh = not (root / ".git").exists()
    if is_fresh:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "branch", "-m", "main"],
            cwd=root, capture_output=True, check=False,
        )

    # Initial commit for fresh repos
    if is_fresh:
        subprocess.run(
            ["git", "add", "."], cwd=root, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial Cambium configuration"],
            cwd=root, capture_output=True, check=False,
        )

    # Optional GitHub remote
    if github:
        _setup_github(root, repo_name)

    return root


def _init_combined(root: Path, framework_dir: Path) -> None:
    """Copy the entire framework into the user directory.

    Existing files are never overwritten — preserves user customizations.
    """
    if not framework_dir.is_dir():
        raise RuntimeError(f"Framework directory not found: {framework_dir}")

    # Copy framework tree, skipping excluded patterns
    _copy_tree(framework_dir, root)

    # Write .cambium-version with framework commit hash
    version_path = root / ".cambium-version"
    if not version_path.exists():
        version = _get_framework_version()
        version_path.write_text(version + "\n")

    # Add upstream remote pointer
    _write_if_missing(
        root / ".cambium-upstream",
        "https://github.com/brayan07/cambium.git\n",
    )

    # Ensure constitution exists at the config level
    config_dir = root / "defaults"
    if config_dir.is_dir():
        _write_if_missing(config_dir / "constitution.md", _get_constitution_template())

    # Ensure .gitignore
    _write_if_missing(root / ".gitignore", _GITIGNORE)


def _init_legacy(root: Path, defaults_dir: Path) -> None:
    """Legacy init — copy defaults/ into root, create config and structure.

    This preserves backward compatibility with the config-only workflow.
    """
    # Ensure core directories
    for d in ("data/memory", "data/sessions", "data/logs", "knowledge"):
        (root / d).mkdir(parents=True, exist_ok=True)

    # Write framework files
    _DEFAULT_CONFIG = {
        "queue": {
            "adapter": "sqlite",
            "database": "data/cambium.db",
        },
    }
    _write_if_missing(
        root / "config.yaml",
        yaml.dump(_DEFAULT_CONFIG, default_flow_style=False),
    )
    _write_if_missing(root / "constitution.md", _get_constitution_template())
    _write_if_missing(root / ".gitignore", "data/\n__pycache__/\n*.pyc\n")

    # Copy defaults tree
    if defaults_dir.is_dir():
        _copy_defaults(defaults_dir, root)


def _copy_tree(src: Path, dst: Path) -> None:
    """Recursively copy src into dst, never overwriting existing files.

    Skips directories matching _COPY_EXCLUDE patterns.
    """
    # Get the ignore function to filter items
    ignore_fn = _COPY_EXCLUDE

    for item in sorted(src.iterdir()):
        # Check if this item should be excluded
        ignored = ignore_fn(str(src), [item.name])
        if item.name in ignored:
            continue

        dest_item = dst / item.name
        if item.is_dir():
            dest_item.mkdir(parents=True, exist_ok=True)
            _copy_tree(item, dest_item)
        elif item.is_file():
            if not dest_item.exists():
                dest_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_item)


def _copy_defaults(defaults_dir: Path, root: Path) -> None:
    """Walk the defaults tree and copy files into the user repo.

    Existing files are never overwritten.
    """
    for src_path in defaults_dir.rglob("*"):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(defaults_dir)
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            continue
        shutil.copy2(src_path, dest)


def _ensure_data_dir(data_dir: Path) -> None:
    """Create the runtime data directory structure."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for subdir in _DATA_DIRS:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)


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
        return

    subprocess.run(
        ["gh", "repo", "create", repo_name,
         "--private", "--source=.", "--remote=origin"],
        cwd=root, check=True,
    )

    # Add upstream remote (for framework updates)
    upstream_file = root / ".cambium-upstream"
    if upstream_file.exists():
        upstream_url = upstream_file.read_text().strip()
        subprocess.run(
            ["git", "remote", "add", "upstream", upstream_url],
            cwd=root, capture_output=True, check=False,
        )

    # Push initial commit BEFORE rewriting to SSH (HTTPS is immediately
    # available; SSH may lag after repo creation).
    push_result = subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=root, capture_output=True, text=True,
    )
    if push_result.returncode != 0:
        log.warning(
            f"GitHub repo created but initial push failed: "
            f"{push_result.stderr.strip() or f'exit code {push_result.returncode}'}"
        )

    # Rewrite origin to SSH if user prefers it (after push)
    proto_result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True,
    )
    if "ssh" in (proto_result.stdout + proto_result.stderr):
        user_result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True,
        )
        gh_user = user_result.stdout.strip()
        if gh_user:
            subprocess.run(
                ["git", "remote", "set-url", "origin",
                 f"git@github.com:{gh_user}/{repo_name}.git"],
                cwd=root, capture_output=True,
            )


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
