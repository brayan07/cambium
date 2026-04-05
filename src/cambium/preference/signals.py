"""Signal extraction: maps work item review events to preference dimension updates."""

from __future__ import annotations

import re
from typing import Any

from cambium.preference.model import Dimension, DimensionState
from cambium.preference.store import PreferenceStore
from cambium.work_item.model import WorkItem

# Observation variance by signal type — lower = more trusted
OBSERVATION_VARIANCE: dict[str, float] = {
    "explicit_statement": 0.01,
    "question_answered": 0.05,
    "review_rejected": 0.05,
    "rejection_feedback": 0.08,
    "review_accepted": 0.20,
}

# Keyword patterns → (dimension_name, signal_value)
# signal_value near 1.0 means "increase this dimension", near 0.0 means "decrease"
FEEDBACK_PATTERNS: dict[str, list[tuple[list[str], float]]] = {
    "research_depth": [
        (["too shallow", "not enough detail", "dig deeper", "needs more", "missing context",
          "need more detail", "more thorough", "not enough sources"], 0.85),
        (["too much detail", "too long", "over-researched", "unnecessary depth",
          "didn't need this much"], 0.15),
    ],
    "brevity": [
        (["too verbose", "too long", "too much", "shorter", "more concise",
          "unnecessary", "trim", "tl;dr", "wordy"], 0.85),
        (["too brief", "too short", "need more", "not enough", "expand"], 0.15),
    ],
    "quality_bar": [
        (["sloppy", "errors", "incorrect", "wrong", "inaccurate", "bugs",
          "broken", "doesn't work", "not accurate"], 0.85),
        (["over-polished", "too much time", "good enough", "don't need perfect"], 0.35),
    ],
    "action_bias": [
        (["should have asked", "wrong direction", "wasted work", "not what I wanted",
          "why didn't you ask", "check first"], 0.15),
        (["took too long", "over-analyzed", "just do it", "stop deliberating",
          "move faster"], 0.85),
    ],
}


def infer_context_key(work_item: WorkItem) -> str:
    """Derive the most specific context key from work item metadata.

    Checks work_item.context for 'domain' and 'task_type' keys.
    """
    domain = work_item.context.get("domain", "")
    task_type = work_item.context.get("task_type", "")

    if domain and task_type:
        return f"domain:{domain}/task_type:{task_type}"
    if domain:
        return f"domain:{domain}"
    return "global"


def extract_signals_from_review(
    work_item: WorkItem,
    verdict: str,
    feedback: str = "",
) -> list[tuple[str, float, float]]:
    """Extract (dimension_name, observation_value, obs_variance) tuples from a review.

    Returns signals to be applied via store.update_posterior().
    """
    signals: list[tuple[str, float, float]] = []

    if verdict == "accepted":
        # Weak positive signal: approval confirms current trajectory
        # We emit a signal at the current dimension mean (reinforcement)
        # with high observation variance (low information density)
        obs_var = OBSERVATION_VARIANCE["review_accepted"]
        for dim_name in FEEDBACK_PATTERNS:
            # Signal value of 0.5 = neutral confirmation (don't shift mean, just reduce variance slightly)
            signals.append((dim_name, 0.5, obs_var))

    elif verdict == "rejected":
        feedback_lower = feedback.lower() if feedback else ""

        matched_dims: set[str] = set()

        if feedback_lower:
            for dim_name, patterns in FEEDBACK_PATTERNS.items():
                for keywords, value in patterns:
                    if any(kw in feedback_lower for kw in keywords):
                        obs_var = OBSERVATION_VARIANCE["rejection_feedback"]
                        signals.append((dim_name, value, obs_var))
                        matched_dims.add(dim_name)
                        break  # one match per dimension per review

        # If no patterns matched but we have a rejection, emit a generic quality signal
        if not matched_dims:
            signals.append(("quality_bar", 0.85, OBSERVATION_VARIANCE["review_rejected"]))

    return signals


def extract_relevant_dimensions(work_item: WorkItem) -> list[str]:
    """Infer which preference dimensions are relevant to a work item."""
    task_type = work_item.context.get("task_type", "").lower()
    title_lower = work_item.title.lower()

    dims = ["quality_bar", "brevity"]  # always relevant

    # Research tasks care about depth
    if task_type == "research" or any(w in title_lower for w in ["research", "investigate", "analyze", "survey"]):
        dims.append("research_depth")

    # All tasks care about action bias and autonomy
    dims.extend(["action_bias", "autonomy_comfort"])

    return list(dict.fromkeys(dims))  # deduplicate preserving order
