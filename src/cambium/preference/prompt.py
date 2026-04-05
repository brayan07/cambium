"""Translate preference state + cases into prompt fragments for routines."""

from __future__ import annotations

from cambium.preference.model import Dimension, DimensionState, PreferenceCase, QueryDecision


def level_label(mean: float) -> str:
    """Convert a [0, 1] mean to a human-readable level."""
    if mean < 0.33:
        return "LOW"
    if mean < 0.66:
        return "MEDIUM"
    return "HIGH"


def confidence_pct(variance: float) -> int:
    """Convert variance to a confidence percentage.

    Lower variance = higher confidence. Assumes initial variance ~0.15-0.20.
    """
    # Map variance 0.0 → 99%, 0.05 → 90%, 0.15 → 70%, 0.25 → 50%
    conf = max(0, min(99, int(100 * (1.0 - variance * 3.0))))
    return conf


def build_preference_prompt(
    dimensions: list[tuple[Dimension, DimensionState]],
    cases: list[PreferenceCase],
    query: QueryDecision | None = None,
) -> str:
    """Build a markdown prompt section from preference state + cases."""
    lines: list[str] = []

    if dimensions:
        lines.append("## Preference Context\n")
        lines.append("### Behavioral Guidance\n")
        for dim, state in dimensions:
            level = level_label(state.mean)
            conf = confidence_pct(state.variance)
            anchor_key = level.lower()
            anchor = dim.anchors.get(anchor_key, "")
            lines.append(f"**{dim.name}: {level}** (confidence: {conf}%, based on {state.update_count} signals)")
            if anchor:
                lines.append(f"  {anchor}")
            lines.append("")

    if cases:
        lines.append("### Relevant Past Cases\n")
        for case in cases:
            direction = "POSITIVE" if case.signal_direction > 0 else "NEGATIVE"
            context_parts = []
            if case.domain:
                context_parts.append(case.domain)
            if case.task_type:
                context_parts.append(case.task_type)
            context_str = "/".join(context_parts) if context_parts else "general"
            lines.append(f"**[{direction}]** {context_str}")
            lines.append(f"  Lesson: {case.lesson}")
            if case.feedback and case.signal_direction < 0:
                lines.append(f"  Feedback: {case.feedback}")
            lines.append("")

    if query and query.should_ask:
        lines.append("### Open Uncertainty\n")
        lines.append(query.question or "")
        lines.append("Consider asking the user before proceeding.\n")

    return "\n".join(lines)
