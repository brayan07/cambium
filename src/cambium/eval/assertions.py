"""Assertion implementations for eval scenarios."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cambium.eval.model import Assertion, AssertionResult

if TYPE_CHECKING:
    from cambium.eval.staging import StagingContext

log = logging.getLogger(__name__)


def check_assertion(ctx: StagingContext, assertion: Assertion) -> AssertionResult:
    """Dispatch to the correct assertion checker based on type."""
    checkers = {
        "episode": assert_episode,
        "work_item_created": assert_work_item_created,
        "no_errors": assert_no_errors,
        "episode_count": assert_episode_count,
        "event_published": assert_event_published,
        "file_exists": assert_file_exists,
        "file_contains": assert_file_contains,
        "memory_committed": assert_memory_committed,
        "llm_rubric": assert_llm_rubric,
        "deterministic": assert_deterministic,
    }
    checker = checkers.get(assertion.type)
    if checker is None:
        return AssertionResult(
            assertion=assertion, passed=False,
            detail=f"Unknown assertion type: {assertion.type}",
        )
    try:
        return checker(ctx, assertion)
    except Exception as e:
        return AssertionResult(
            assertion=assertion, passed=False,
            detail=f"Assertion error: {e}",
        )


def assert_episode(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that an episode exists for a given routine with expected status."""
    episodes = ctx.episodes(routine=a.routine, limit="50")
    matching = [
        ep for ep in episodes
        if (a.status is None or ep.get("status") == a.status)
    ]
    if matching:
        return AssertionResult(
            assertion=a, passed=True,
            detail=f"Found {len(matching)} episode(s) for {a.routine}",
        )
    return AssertionResult(
        assertion=a, passed=False,
        detail=f"No episode for routine={a.routine} with status={a.status}. "
               f"Found {len(episodes)} total episodes for this routine.",
    )


def assert_work_item_created(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that a work item was created containing expected text in title."""
    items = ctx.work_items(limit="50")
    if a.title_contains:
        matching = [
            wi for wi in items
            if a.title_contains.lower() in wi.get("title", "").lower()
        ]
    else:
        matching = items

    if matching:
        return AssertionResult(
            assertion=a, passed=True,
            detail=f"Found {len(matching)} matching work item(s)",
        )
    return AssertionResult(
        assertion=a, passed=False,
        detail=f"No work item with title containing '{a.title_contains}'. "
               f"Found {len(items)} total work items.",
    )


def assert_no_errors(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that no episodes have error status."""
    episodes = ctx.episodes(limit="100")
    errors = [ep for ep in episodes if ep.get("status") == "error"]
    if errors:
        routines = [ep.get("routine", "?") for ep in errors]
        return AssertionResult(
            assertion=a, passed=False,
            detail=f"{len(errors)} error episode(s): {routines}",
        )
    return AssertionResult(assertion=a, passed=True)


def assert_episode_count(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check episode count for a routine is within bounds."""
    episodes = ctx.episodes(routine=a.routine, limit="100")
    count = len(episodes)
    min_count = a.min or 0
    max_count = a.max or float("inf")

    if min_count <= count <= max_count:
        return AssertionResult(
            assertion=a, passed=True,
            detail=f"{count} episodes for {a.routine} (expected {min_count}-{max_count})",
        )
    return AssertionResult(
        assertion=a, passed=False,
        detail=f"{count} episodes for {a.routine} (expected {min_count}-{max_count})",
    )


def assert_event_published(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that an event was published to a specific channel."""
    events = ctx.events(channel=a.channel, limit="50")
    if events:
        return AssertionResult(
            assertion=a, passed=True,
            detail=f"Found {len(events)} event(s) on channel {a.channel}",
        )
    return AssertionResult(
        assertion=a, passed=False,
        detail=f"No events on channel {a.channel}",
    )


def assert_file_exists(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that a file exists in the staging data directory."""
    path = ctx.data_dir / a.path if a.path else None
    if path and path.exists():
        return AssertionResult(assertion=a, passed=True, detail=str(path))
    return AssertionResult(
        assertion=a, passed=False,
        detail=f"File not found: {a.path}",
    )


def assert_file_contains(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that a file contains a pattern."""
    import re
    path = ctx.data_dir / a.path if a.path else None
    if not path or not path.exists():
        return AssertionResult(
            assertion=a, passed=False, detail=f"File not found: {a.path}",
        )
    content = path.read_text()
    if a.pattern and re.search(a.pattern, content):
        return AssertionResult(assertion=a, passed=True)
    return AssertionResult(
        assertion=a, passed=False,
        detail=f"Pattern '{a.pattern}' not found in {a.path}",
    )


def assert_memory_committed(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Check that the memory service has git commits."""
    memory_dir = ctx.data_dir / "memory"
    if not (memory_dir / ".git").exists():
        return AssertionResult(
            assertion=a, passed=False, detail="No memory git repo found",
        )
    result = subprocess.run(
        ["git", "log", "--oneline", "-5"],
        capture_output=True, cwd=str(memory_dir),
    )
    commits = result.stdout.decode().strip()
    if commits:
        return AssertionResult(
            assertion=a, passed=True, detail=f"Memory commits:\n{commits}",
        )
    return AssertionResult(
        assertion=a, passed=False, detail="No commits in memory repo",
    )


def assert_llm_rubric(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Evaluate using an LLM rubric (calls claude -p with haiku)."""
    # Resolve the target — could be a work item field, episode output, etc.
    target_text = _resolve_target(ctx, a.target or "")
    if not target_text:
        return AssertionResult(
            assertion=a, passed=False,
            detail=f"Could not resolve target: {a.target}",
        )

    rubric = a.rubric or "Evaluate the quality of the output."
    threshold = a.threshold or 0.7

    prompt = (
        f"You are evaluating the output of an AI agent. "
        f"Score from 0.0 to 1.0 based on this rubric:\n\n"
        f"RUBRIC:\n{rubric}\n\n"
        f"OUTPUT TO EVALUATE:\n{target_text}\n\n"
        f"Respond with ONLY a JSON object: {{\"score\": <float>, \"reasoning\": \"<brief>\"}}"
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True, timeout=60,
        )
        import json
        response = result.stdout.decode().strip()
        # Try to extract JSON from the response
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                score = float(data.get("score", 0))
                reasoning = data.get("reasoning", "")
                passed = score >= threshold
                return AssertionResult(
                    assertion=a, passed=passed, score=score,
                    detail=f"Score: {score:.2f} (threshold: {threshold}). {reasoning}",
                )
        return AssertionResult(
            assertion=a, passed=False,
            detail=f"Could not parse LLM response: {response[:200]}",
        )
    except Exception as e:
        return AssertionResult(
            assertion=a, passed=False, detail=f"LLM rubric error: {e}",
        )


def assert_deterministic(ctx: StagingContext, a: Assertion) -> AssertionResult:
    """Run a deterministic grader script and check the result."""
    if not a.path:
        return AssertionResult(
            assertion=a, passed=False, detail="No script path specified",
        )
    try:
        import os
        # Resolve script path relative to the worktree (config override repo) or
        # fall back to the original repo dir.  The staging context carries the
        # worktree_dir when config overrides created one.
        script_path = Path(a.path)
        if not script_path.is_absolute():
            # Try the working directory first (original repo), then the worktree.
            # Worktrees may not have uncommitted files like new eval scripts.
            for base in [Path.cwd(), ctx.worktree_dir]:
                if base and (base / script_path).exists():
                    script_path = base / script_path
                    break
            else:
                return AssertionResult(
                    assertion=a, passed=False,
                    detail=f"Script not found: {a.path} (tried cwd={Path.cwd()}, "
                           f"worktree={ctx.worktree_dir})",
                )
        # Inherit PATH so the script can find system commands (find, grep, etc.)
        env = {
            "STAGING_API_URL": ctx.api_url,
            "STAGING_DATA_DIR": str(ctx.data_dir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True, timeout=60,
            cwd=str(ctx.data_dir),
            env=env,
        )
        import json
        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode().strip()
        if not stdout:
            return AssertionResult(
                assertion=a, passed=False,
                detail=f"Script produced no output. stderr: {stderr[:500]}. "
                       f"path: {script_path}, rc: {result.returncode}",
            )
        data = json.loads(stdout)
        score = float(data.get("score", 0))
        detail = data.get("details", "")
        threshold = a.threshold or 0.5
        return AssertionResult(
            assertion=a, passed=score >= threshold, score=score, detail=detail,
        )
    except Exception as e:
        return AssertionResult(
            assertion=a, passed=False, detail=f"Script error: {e}",
        )


def _resolve_target(ctx: StagingContext, target: str) -> str | None:
    """Resolve a target reference to actual text content.

    Supports:
    - "work_item.description" — first work item's description
    - "work_item.result" — first work item's result
    - "episode.output" — first episode's output
    """
    parts = target.split(".", 1)
    if len(parts) != 2:
        return None

    entity, field = parts

    if entity == "work_item":
        items = ctx.work_items(limit="1")
        if items:
            return items[0].get(field, "")
    elif entity == "episode":
        episodes = ctx.episodes(limit="1")
        if episodes:
            return episodes[0].get(field, "")
    return None
