#!/usr/bin/env python3
"""Claude Code PreToolUse hook — block edits inside the live Cambium repo.

Defense-in-depth guardrail for brayan07/cambium#30. The self-improvement skill
already says "use git worktree before editing repo files," but if classification
fails the executor never invokes the skill and writes directly to the live tree.
This hook is a runtime safety net: regardless of which skill fired (or didn't),
any Edit/Write/MultiEdit/NotebookEdit whose ``file_path`` resolves inside
``$CAMBIUM_REPO_DIR`` is refused with a reason that points at the right fix.

The hook reads a single JSON object from stdin (Claude Code's PreToolUse
contract) and writes a single JSON object to stdout. Returning a non-zero
exit with ``decision=block`` causes Claude Code to surface the reason to the
model as a tool error so it can self-correct on the next turn.

Bypass: when ``CAMBIUM_REPO_DIR`` is unset or empty, the hook is a no-op.
This keeps it safe to install unconditionally — non-Cambium contexts and
worktrees outside the live tree pass through.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Tools that mutate files on disk. NotebookEdit is included even though
# it operates on .ipynb cells because its file_path is still a real path.
_FILE_MUTATING_TOOLS: frozenset[str] = frozenset({
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
})

# Only paths *inside* one of these subdirectories of the repo are gated.
# A free-form file at the repo root (e.g. ``hello.txt``, scratch notes) is
# not source code and should not be blocked — that would break the canary
# scenario "create hello.txt" without addressing the actual #30 vector.
# Keep this list in sync with cambium.work_item.classifier prefixes.
_GATED_SUBDIRS: tuple[str, ...] = (
    "src",
    "tests",
    "test",
    "defaults",
    "ui/src",
    "ui/public",
    "scripts",
)

# Top-level files that are also gated when targeted directly.
_GATED_TOP_LEVEL_FILES: frozenset[str] = frozenset({
    "pyproject.toml",
    "package.json",
    "uv.lock",
    "package-lock.json",
    "tunable-manifest.yaml",
    ".cambium-version",
})


def main() -> int:
    repo_dir_str = os.environ.get("CAMBIUM_REPO_DIR", "").strip()
    if not repo_dir_str:
        # Hook is a no-op when no repo to protect.
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed input — fail open rather than block legitimate work.
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in _FILE_MUTATING_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(file_path, str) or not file_path:
        return 0

    try:
        repo_dir = Path(repo_dir_str).resolve()
    except (OSError, RuntimeError):
        return 0

    target = Path(file_path)
    if not target.is_absolute():
        # Resolve relative to current working directory — same semantics
        # Claude Code uses for relative file_path arguments.
        target = (Path.cwd() / target)
    try:
        target = target.resolve()
    except (OSError, RuntimeError):
        # Path doesn't exist yet; resolve parents we can.
        try:
            target = (target.parent.resolve() / target.name)
        except (OSError, RuntimeError):
            return 0

    if not _is_inside(target, repo_dir):
        return 0

    if not _is_gated_within_repo(target, repo_dir):
        return 0

    reason = (
        f"Refusing to {tool_name} {target} — this path is inside the live "
        f"Cambium repo at {repo_dir}. Self-improvement edits MUST go through "
        "a git worktree outside the live tree (see the cambium-self-improvement "
        "skill's references/execution.md). Run `git worktree add "
        "/tmp/cambium-improve-$$ -b <branch>` and cd into that worktree before "
        "calling Edit/Write again."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }))
    return 0


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_gated_within_repo(path: Path, repo_dir: Path) -> bool:
    """True if ``path`` (already known to be inside ``repo_dir``) is one of
    the gated source paths the self-improvement loop must not bypass.

    Anything else inside the repo (scratch files at the root, eval outputs,
    user-created notes) is allowed through. This mirrors the path classifier
    used for auto-classification of work items.
    """
    try:
        rel = path.relative_to(repo_dir)
    except ValueError:
        return False
    parts = rel.parts
    if not parts:
        return False
    if len(parts) == 1 and parts[0] in _GATED_TOP_LEVEL_FILES:
        return True
    # Match single-segment subdirs (src, tests, defaults, scripts).
    if parts[0] in {"src", "tests", "test", "defaults", "scripts"}:
        return True
    # Match two-segment prefixes (ui/src, ui/public).
    if len(parts) >= 2 and f"{parts[0]}/{parts[1]}" in {"ui/src", "ui/public"}:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
