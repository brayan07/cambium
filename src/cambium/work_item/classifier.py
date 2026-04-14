"""Auto-classification helpers for work items.

Detects when a proposed work item targets paths that should flow through the
self-improvement PR pipeline (worktree + eval + PR + review), and forces the
``context.type`` field to ``self_improvement`` so the planner picks the
PR-gated decomposition.

This is fix (a) for brayan07/cambium#30: without it, work items whose target
files live under ``src/``, ``tests/``, ``defaults/``, ``ui/src/``, etc. were
classified as ordinary implementation tasks and bypassed the PR gate entirely.
"""

from __future__ import annotations

import re
from typing import Any

# Path prefixes (relative to repo root) whose modification must go through
# the self-improvement PR pipeline. Matches both POSIX and Windows separators.
_SELF_IMPROVEMENT_PATH_PREFIXES: tuple[str, ...] = (
    "src/",
    "tests/",
    "test/",
    "defaults/",
    "ui/src/",
    "ui/public/",
    "scripts/",
)

# Top-level files that are also self-improvement-gated when targeted directly.
_SELF_IMPROVEMENT_FILES: frozenset[str] = frozenset({
    "pyproject.toml",
    "package.json",
    "uv.lock",
    "package-lock.json",
    "tunable-manifest.yaml",
    ".cambium-version",
})

# Match a path token in free-form text. We look for a slash-separated token
# whose first segment is one of the prefixes above, OR a bare top-level filename
# from the set above. The match is anchored on a non-word boundary on the left
# so we don't catch things like "mysrc/foo.py".
_PATH_TOKEN_RE = re.compile(
    r"(?:(?<=\s)|(?<=[\"'`(\[<])|^)"
    r"((?:src|tests?|defaults|ui/src|ui/public|scripts)/[\w./\-]+|"
    r"(?:pyproject\.toml|package\.json|uv\.lock|package-lock\.json|"
    r"tunable-manifest\.yaml|\.cambium-version))\b"
)


def looks_like_self_improvement(
    title: str = "",
    description: str = "",
    context: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Return (is_self_improvement, matched_paths).

    A work item is classified as self-improvement when its title, description,
    or context fields reference at least one path that lives under a
    self-improvement-gated prefix (see ``_SELF_IMPROVEMENT_PATH_PREFIXES``) or
    one of the top-level gated files.

    Pure function — no I/O. Used at work-item creation time.
    """
    matched: list[str] = []

    # 1. Explicit target_file in context — highest signal.
    ctx = context or {}
    target = ctx.get("target_file")
    if isinstance(target, str) and _path_is_gated(target):
        matched.append(target)

    affected = ctx.get("affected_paths")
    if isinstance(affected, list):
        for p in affected:
            if isinstance(p, str) and _path_is_gated(p):
                matched.append(p)

    # 2. Free-form scan of title + description.
    haystack = f"{title}\n{description}"
    for m in _PATH_TOKEN_RE.finditer(haystack):
        token = m.group(1)
        if _path_is_gated(token):
            matched.append(token)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for p in matched:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    return (len(deduped) > 0, deduped)


def _path_is_gated(path: str) -> bool:
    """True if ``path`` is under a self-improvement-gated prefix or filename."""
    if not path:
        return False
    norm = path.strip().lstrip("./").replace("\\", "/")
    if norm in _SELF_IMPROVEMENT_FILES:
        return True
    return any(norm.startswith(prefix) for prefix in _SELF_IMPROVEMENT_PATH_PREFIXES)


def auto_classify(
    title: str,
    description: str,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a context dict augmented with self-improvement classification.

    If the existing context already has ``type`` set, it is left alone — the
    caller's explicit classification wins. Otherwise, if the title/description/
    context references self-improvement-gated paths, ``type`` is set to
    ``self_improvement`` and ``auto_classified`` is set to ``True`` with the
    matched paths recorded under ``classified_targets`` for traceability.
    """
    ctx: dict[str, Any] = dict(context or {})
    if ctx.get("type"):
        return ctx

    is_si, matched = looks_like_self_improvement(title, description, ctx)
    if not is_si:
        return ctx

    ctx["type"] = "self_improvement"
    ctx["auto_classified"] = True
    ctx["classified_targets"] = matched
    return ctx
