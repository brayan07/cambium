"""Case library: building and retrieving learning examples (CBR)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from cambium.preference.model import PreferenceCase
from cambium.preference.signals import infer_context_key
from cambium.preference.store import PreferenceStore
from cambium.work_item.model import WorkItem


def build_case_from_review(
    work_item: WorkItem,
    verdict: str,
    feedback: str = "",
    lesson: str | None = None,
) -> PreferenceCase:
    """Construct a PreferenceCase from a reviewed work item.

    The lesson parameter is provided externally (by the consolidator LLM).
    If not provided, falls back to the feedback text or a generic message.
    """
    if lesson is None:
        if feedback:
            lesson = feedback
        elif verdict == "accepted":
            lesson = "Approach was acceptable for this context."
        else:
            lesson = "Task was rejected without specific feedback."

    signal_direction = 1.0 if verdict == "accepted" else -1.0

    return PreferenceCase.create(
        work_item_id=work_item.id,
        domain=work_item.context.get("domain", ""),
        task_type=work_item.context.get("task_type", ""),
        goal_areas=work_item.context.get("goal_areas", []),
        priority=work_item.priority,
        action_summary=work_item.result or work_item.title,
        outcome=f"{verdict}: {work_item.result or 'no result'}"[:500],
        feedback=feedback or None,
        lesson=lesson,
        signal_direction=signal_direction,
    )


def retrieve_relevant_cases(
    work_item: WorkItem,
    store: PreferenceStore,
    limit: int = 3,
) -> list[PreferenceCase]:
    """Retrieve the most relevant cases for a work item, scored by similarity."""
    domain = work_item.context.get("domain", "")
    task_type = work_item.context.get("task_type", "")

    # Fetch candidates — broader query, score in Python
    candidates = store.query_cases(limit=50)

    if not candidates:
        return []

    scored: list[tuple[float, PreferenceCase]] = []
    for case in candidates:
        score = _score_case(work_item, case, domain, task_type)
        scored.append((score, case))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for _, case in scored[:limit]:
        store.update_case_retrieval(case.id)
        results.append(case)

    return results


def _score_case(
    work_item: WorkItem,
    case: PreferenceCase,
    domain: str,
    task_type: str,
) -> float:
    """Score a case for relevance to a work item."""
    score = 0.0

    # Domain match (strongest signal)
    if case.domain and case.domain == domain:
        score += 0.35

    # Task type match
    if case.task_type and case.task_type == task_type:
        score += 0.20

    # Priority similarity (closer is better)
    priority_diff = abs(case.priority - work_item.priority)
    score += max(0.0, 0.10 - priority_diff * 0.02)

    # Recency: exponential decay with 30-day half-life
    age_days = _days_since(case.created_at)
    score += 0.20 * (0.5 ** (age_days / 30.0))

    # Proven usefulness
    score += 0.15 * case.usefulness_score

    return score


def _days_since(iso_timestamp: str) -> float:
    """Days between an ISO timestamp and now."""
    try:
        created = datetime.fromisoformat(iso_timestamp)
        now = datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (now - created).total_seconds() / 86400.0)
    except (ValueError, TypeError):
        return 30.0  # fallback: treat unparseable as ~1 month old
