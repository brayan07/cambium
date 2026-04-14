"""Tests for the protect-repo PreToolUse hook (fix (b) for #30).

The hook script lives under ``defaults/adapters/claude-code/hooks/protect-repo.py``
and is invoked by Claude Code with a JSON payload on stdin. These tests exec
the hook as a subprocess and verify it blocks edits inside CAMBIUM_REPO_DIR
while passing other paths through.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "defaults" / "adapters" / "claude-code" / "hooks" / "protect-repo.py"


def _run_hook(payload: dict, env_repo_dir: str | None) -> tuple[int, dict | None]:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    if env_repo_dir is not None:
        env["CAMBIUM_REPO_DIR"] = env_repo_dir
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    out = proc.stdout.strip()
    parsed = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed


def test_block_edit_inside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    target = repo / "src" / "cambium" / "foo.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n")

    rc, out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is not None
    decision = out.get("hookSpecificOutput", {})
    assert decision.get("permissionDecision") == "deny"
    reason = decision.get("permissionDecisionReason", "")
    assert "worktree" in reason.lower()
    assert "Cambium repo" in reason


def test_block_write_inside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    target = repo / "src" / "new_file.py"

    rc, out = _run_hook(
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_allow_edit_outside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    other = tmp_path / "other" / "file.py"
    other.parent.mkdir()
    other.write_text("y = 2\n")

    rc, out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": str(other)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is None  # no JSON output → allow


def test_allow_edit_in_worktree_outside_repo(tmp_path: Path) -> None:
    """Edits in a worktree path that does not nest inside the live repo pass."""
    repo = tmp_path / "cambium"
    repo.mkdir()
    worktree = tmp_path / "worktrees" / "fix-30" / "src" / "cambium" / "foo.py"
    worktree.parent.mkdir(parents=True)
    worktree.write_text("x = 1\n")

    rc, out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": str(worktree)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is None


def test_no_op_when_repo_dir_unset(tmp_path: Path) -> None:
    target = tmp_path / "anywhere" / "foo.py"
    target.parent.mkdir()
    rc, out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
        env_repo_dir=None,
    )
    assert rc == 0
    assert out is None


def test_passes_through_non_file_tools(tmp_path: Path) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    rc, out = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is None


def test_passes_through_malformed_input(tmp_path: Path) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    # Missing tool_input
    rc, out = _run_hook({"tool_name": "Edit"}, env_repo_dir=str(repo))
    assert rc == 0
    assert out is None


def test_blocks_multiedit_inside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    target = repo / "src" / "x.py"
    target.parent.mkdir(parents=True)
    rc, out = _run_hook(
        {"tool_name": "MultiEdit", "tool_input": {"file_path": str(target)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_allow_scratch_file_at_repo_root(tmp_path: Path) -> None:
    """A free-form file at the repo root (e.g. hello.txt) is not source code
    and must not be blocked — that would break the canary 'create hello.txt'
    scenario without addressing the actual #30 vector."""
    repo = tmp_path / "cambium"
    repo.mkdir()
    target = repo / "hello.txt"
    rc, out = _run_hook(
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is None


def test_block_pyproject_toml_at_repo_root(tmp_path: Path) -> None:
    """Top-level files like pyproject.toml ARE gated — they're tunables."""
    repo = tmp_path / "cambium"
    repo.mkdir()
    target = repo / "pyproject.toml"
    rc, out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_blocks_relative_path_resolved_against_cwd(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "cambium"
    repo.mkdir()
    sub = repo / "src"
    sub.mkdir()
    monkeypatch.chdir(sub)
    rc, out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": "foo.py"}},
        env_repo_dir=str(repo),
    )
    assert rc == 0
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
