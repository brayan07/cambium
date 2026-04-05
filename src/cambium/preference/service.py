"""Business logic for preference learning: signal processing, context building, case management."""

from __future__ import annotations

import logging
from typing import Any

from cambium.preference.cases import build_case_from_review, retrieve_relevant_cases
from cambium.preference.model import (
    Dimension,
    DimensionState,
    ObjectiveDefinition,
    ObjectiveReport,
    PreferenceCase,
    QueryDecision,
    Signal,
)
from cambium.preference.prompt import build_preference_prompt
from cambium.preference.signals import (
    extract_relevant_dimensions,
    extract_signals_from_review,
    infer_context_key,
)
from cambium.preference.store import PreferenceStore
from cambium.work_item.model import WorkItem

logger = logging.getLogger(__name__)

# Default initial dimensions — can be overridden by initialize_from_constitution()
INITIAL_DIMENSIONS = [
    {
        "name": "research_depth",
        "description": "How thorough to be when investigating a topic",
        "anchors": {
            "low": "Quick answer from existing knowledge, 1-2 sentences, no source verification",
            "medium": "2-3 source check, paragraph summary with confidence markers",
            "high": "Comprehensive multi-source analysis, adversarial search on constraints, confidence ratings",
        },
        "constitutional_source": "goal:2",
        "initial_mean": 0.65,
        "initial_variance": 0.15,
    },
    {
        "name": "autonomy_comfort",
        "description": "How much to proceed without user input vs. asking for guidance",
        "anchors": {
            "low": "Ask before every non-trivial decision",
            "medium": "Proceed on routine tasks, ask on novel or high-stakes work",
            "high": "Proceed unless genuinely uncertain on a high-stakes decision",
        },
        "constitutional_source": "virtue:courage",
        "initial_mean": 0.50,
        "initial_variance": 0.20,
    },
    {
        "name": "quality_bar",
        "description": "How polished and accurate output needs to be",
        "anchors": {
            "low": "Rough drafts acceptable, speed over polish",
            "medium": "Clean and correct, but not publication-ready",
            "high": "Publication-ready, adversarially reviewed, no errors",
        },
        "constitutional_source": "virtue:wisdom",
        "initial_mean": 0.60,
        "initial_variance": 0.15,
    },
    {
        "name": "brevity",
        "description": "How concise vs. comprehensive output should be",
        "anchors": {
            "low": "Comprehensive, include all relevant context and detail",
            "medium": "Structured with executive summary, details available but skimmable",
            "high": "Minimal — just the answer, no preamble or padding",
        },
        "constitutional_source": "feedback",
        "initial_mean": 0.60,
        "initial_variance": 0.15,
    },
    {
        "name": "action_bias",
        "description": "Whether to ship imperfect work now or wait for clarity",
        "anchors": {
            "low": "Wait for clarity, avoid wasted work, ask before acting",
            "medium": "Balanced — act on routine, pause on ambiguous",
            "high": "Ship imperfect now, iterate after, don't over-analyze",
        },
        "constitutional_source": "virtue:courage",
        "initial_mean": 0.55,
        "initial_variance": 0.18,
    },
]

INITIAL_OBJECTIVES = [
    {"name": "mood", "constitutional_goal": "goal:1",
     "description": "Overall emotional state", "cadence": "daily"},
    {"name": "mental_clarity", "constitutional_goal": "goal:1",
     "description": "Cognitive sharpness, focus, lack of fog", "cadence": "daily"},
    {"name": "physical_vitality", "constitutional_goal": "goal:1",
     "description": "Physical energy, exercise consistency, body feel", "cadence": "weekly"},
    {"name": "intellectual_growth", "constitutional_goal": "goal:2",
     "description": "Sense of learning, curiosity satisfied, understanding deepened", "cadence": "weekly"},
    {"name": "contribution_sense", "constitutional_goal": "goal:3",
     "description": "Feeling of contributing to others' wellbeing", "cadence": "weekly"},
]


class PreferenceService:
    """Wraps PreferenceStore with signal processing, context building, and case management."""

    def __init__(self, store: PreferenceStore) -> None:
        self.store = store

    # ── Initialization ──────────────────────────────────────────────

    def initialize_defaults(self) -> None:
        """Seed default dimensions and objectives. Idempotent — skips existing."""
        for spec in INITIAL_DIMENSIONS:
            existing = self.store.get_dimension_by_name(spec["name"])
            if existing is not None:
                continue
            dim = Dimension.create(
                name=spec["name"],
                description=spec["description"],
                anchors=spec["anchors"],
                constitutional_source=spec["constitutional_source"],
            )
            self.store.create_dimension(dim)
            self.store.set_state(dim.id, "global", spec["initial_mean"], spec["initial_variance"])
            logger.info(f"Initialized preference dimension: {spec['name']}")

        for spec in INITIAL_OBJECTIVES:
            existing = self.store.get_objective_by_name(spec["name"])
            if existing is not None:
                continue
            obj = ObjectiveDefinition.create(
                name=spec["name"],
                constitutional_goal=spec["constitutional_goal"],
                description=spec["description"],
                cadence=spec["cadence"],
            )
            self.store.create_objective(obj)
            logger.info(f"Initialized objective: {spec['name']}")

    # ── Signal processing ───────────────────────────────────────────

    def process_review(
        self,
        work_item: WorkItem,
        verdict: str,
        feedback: str = "",
        actor: str | None = None,
    ) -> list[Signal]:
        """Extract preference signals from a review and update posteriors.

        Called synchronously from WorkItemService.review_item().
        """
        raw_signals = extract_signals_from_review(work_item, verdict, feedback)
        context_key = infer_context_key(work_item)

        recorded: list[Signal] = []
        for dim_name, observation, obs_variance in raw_signals:
            dim = self.store.get_dimension_by_name(dim_name)
            if dim is None:
                continue

            # Try context-specific state first, fall back to global
            state = self.store.resolve_state(dim.id, [context_key, "global"])
            if state is None:
                continue

            # Use the state's context key for the update
            update_key = context_key if self.store.get_state(dim.id, context_key) else "global"

            signal = self.store.update_posterior(
                dimension_id=dim.id,
                context_key=update_key,
                observation=observation,
                obs_variance=obs_variance,
                source_item_id=work_item.id,
                signal_type=f"review_{verdict}",
                raw_data={"verdict": verdict, "feedback": feedback, "actor": actor},
            )
            recorded.append(signal)

        return recorded

    # ── Context building ────────────────────────────────────────────

    def build_preference_context(self, work_item: WorkItem) -> dict[str, Any]:
        """Build the full preference context for a work item.

        Returns a dict suitable for JSON serialization and prompt injection.
        """
        context_key = infer_context_key(work_item)
        relevant_dim_names = extract_relevant_dimensions(work_item)

        # Gather dimension states
        dim_states: list[tuple[Dimension, DimensionState]] = []
        for name in relevant_dim_names:
            dim = self.store.get_dimension_by_name(name)
            if dim is None:
                continue
            state = self.store.resolve_state(dim.id, [context_key, "global"])
            if state is None:
                continue
            dim_states.append((dim, state))

        # Retrieve relevant cases
        cases = retrieve_relevant_cases(work_item, self.store, limit=3)

        # Build prompt text
        prompt_text = build_preference_prompt(dim_states, cases)

        return {
            "dimensions": [
                {
                    "name": dim.name,
                    "level": _level_label(state.mean),
                    "mean": round(state.mean, 3),
                    "variance": round(state.variance, 4),
                    "confidence_pct": _confidence_pct(state.variance),
                    "update_count": state.update_count,
                    "context_key": state.context_key,
                    "anchor": dim.anchors.get(_level_label(state.mean).lower(), ""),
                }
                for dim, state in dim_states
            ],
            "cases": [
                {
                    "id": c.id,
                    "domain": c.domain,
                    "task_type": c.task_type,
                    "lesson": c.lesson,
                    "signal_direction": c.signal_direction,
                    "feedback": c.feedback,
                }
                for c in cases
            ],
            "prompt_text": prompt_text,
        }

    # ── Case management ─────────────────────────────────────────────

    def create_case_from_review(
        self,
        work_item: WorkItem,
        verdict: str,
        feedback: str = "",
        lesson: str | None = None,
    ) -> PreferenceCase:
        """Build and store a case from a reviewed work item."""
        case = build_case_from_review(work_item, verdict, feedback, lesson)
        self.store.create_case(case)
        return case

    def retrieve_cases(self, work_item: WorkItem, limit: int = 3) -> list[PreferenceCase]:
        """Retrieve relevant cases for a work item."""
        return retrieve_relevant_cases(work_item, self.store, limit=limit)

    def record_case_outcome(self, case_id: str, task_approved: bool) -> None:
        """Update case usefulness based on task outcome."""
        delta = 0.05 if task_approved else -0.05
        self.store.update_case_usefulness(case_id, delta)

    # ── Objectives ──────────────────────────────────────────────────

    def record_objective(
        self,
        objective_name: str,
        value: float,
        notes: str | None = None,
    ) -> ObjectiveReport:
        obj = self.store.get_objective_by_name(objective_name)
        if obj is None:
            raise ValueError(f"Objective '{objective_name}' not found")
        report = ObjectiveReport.create(
            objective_id=obj.id, value=value, notes=notes,
        )
        self.store.record_objective_report(report)
        return report


def _level_label(mean: float) -> str:
    if mean < 0.33:
        return "LOW"
    if mean < 0.66:
        return "MEDIUM"
    return "HIGH"


def _confidence_pct(variance: float) -> int:
    return max(0, min(99, int(100 * (1.0 - variance * 3.0))))
