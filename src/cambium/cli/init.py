"""Bootstrap the Cambium user data repository."""

from pathlib import Path
import subprocess
import yaml


_DEFAULT_CONFIG = {
    "framework_path": None,
    "queue": {
        "adapter": "sqlite",
        "database": "data/cambium.db",
    },
}

_GITIGNORE = "data/\n__pycache__/\n*.pyc\n"

_CONSTITUTION = "# Constitution\n\nDefine your values, goals, and priorities here.\n"

_DIRS = [
    "skills",
    "routines",
    "knowledge",
    "data/memory",
    "data/sessions",
    "data/logs",
]


def init_user_repo(base_path: Path | None = None) -> Path:
    """Create the ~/.cambium/ directory structure.

    Args:
        base_path: Override the default ~/.cambium/ location (useful for testing).

    Returns:
        The path to the initialised user repo.
    """
    root = base_path or Path.home() / ".cambium"
    root.mkdir(parents=True, exist_ok=True)

    # Create directories
    for d in _DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    # Write files only if they don't exist (idempotent)
    _write_if_missing(root / "config.yaml", yaml.dump(_DEFAULT_CONFIG, default_flow_style=False))
    _write_if_missing(root / "constitution.md", _CONSTITUTION)
    _write_if_missing(root / ".gitignore", _GITIGNORE)

    # Init git repo if not already one
    if not (root / ".git").exists():
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-m", "main"], cwd=root, capture_output=True, check=False)

    return root


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content)
