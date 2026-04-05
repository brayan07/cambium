"""Preference learning data models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Dimension:
    """A named behavioral preference dimension with scale anchors."""

    id: str
    name: str
    description: str
    anchors: dict[str, str]  # {"low": "...", "medium": "...", "high": "..."}
    constitutional_source: str | None  # "goal:2", "virtue:wisdom", etc.
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        name: str,
        description: str = "",
        anchors: dict[str, str] | None = None,
        constitutional_source: str | None = None,
    ) -> Dimension:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            anchors=anchors or {},
            constitutional_source=constitutional_source,
            created_at=now,
            updated_at=now,
        )


@dataclass
class DimensionState:
    """Current Gaussian posterior for a dimension in a specific context."""

    dimension_id: str
    context_key: str  # "global", "domain:career", "domain:career/task_type:research"
    mean: float
    variance: float
    update_count: int
    created_at: str
    updated_at: str


@dataclass
class Signal:
    """A single preference observation with before/after posterior snapshots."""

    id: str
    dimension_id: str
    context_key: str
    signal_type: str  # review_accepted, review_rejected, rejection_feedback, etc.
    signal_value: float
    observation_variance: float
    prior_mean: float
    prior_variance: float
    posterior_mean: float
    posterior_variance: float
    source_item_id: str | None
    raw_data: dict[str, Any]
    created_at: str

    @classmethod
    def create(
        cls,
        dimension_id: str,
        context_key: str,
        signal_type: str,
        signal_value: float,
        observation_variance: float,
        prior_mean: float,
        prior_variance: float,
        posterior_mean: float,
        posterior_variance: float,
        source_item_id: str | None = None,
        raw_data: dict[str, Any] | None = None,
    ) -> Signal:
        return cls(
            id=str(uuid.uuid4()),
            dimension_id=dimension_id,
            context_key=context_key,
            signal_type=signal_type,
            signal_value=signal_value,
            observation_variance=observation_variance,
            prior_mean=prior_mean,
            prior_variance=prior_variance,
            posterior_mean=posterior_mean,
            posterior_variance=posterior_variance,
            source_item_id=source_item_id,
            raw_data=raw_data or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass
class PreferenceCase:
    """A learning example from a reviewed work item (CBR case)."""

    id: str
    work_item_id: str
    domain: str
    task_type: str
    goal_areas: list[str]
    priority: int
    action_summary: str
    outcome: str
    feedback: str | None
    lesson: str
    dimensions_affected: list[str]
    signal_direction: float  # +1 positive example, -1 negative
    retrieval_count: int
    usefulness_score: float
    archived: bool
    created_at: str
    last_retrieved_at: str | None

    @classmethod
    def create(
        cls,
        work_item_id: str,
        action_summary: str,
        outcome: str,
        lesson: str,
        domain: str = "",
        task_type: str = "",
        goal_areas: list[str] | None = None,
        priority: int = 0,
        feedback: str | None = None,
        dimensions_affected: list[str] | None = None,
        signal_direction: float = 0.0,
    ) -> PreferenceCase:
        return cls(
            id=str(uuid.uuid4()),
            work_item_id=work_item_id,
            domain=domain,
            task_type=task_type,
            goal_areas=goal_areas or [],
            priority=priority,
            action_summary=action_summary,
            outcome=outcome,
            feedback=feedback,
            lesson=lesson,
            dimensions_affected=dimensions_affected or [],
            signal_direction=signal_direction,
            retrieval_count=0,
            usefulness_score=0.5,
            archived=False,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_retrieved_at=None,
        )


@dataclass
class ObjectiveDefinition:
    """A measurable wellbeing proxy tied to a constitutional goal."""

    id: str
    name: str
    constitutional_goal: str  # "goal:1", "goal:2", "goal:3"
    description: str
    scale_min: float
    scale_max: float
    cadence: str  # "daily", "weekly"
    created_at: str

    @classmethod
    def create(
        cls,
        name: str,
        constitutional_goal: str,
        description: str = "",
        scale_min: float = 1.0,
        scale_max: float = 5.0,
        cadence: str = "weekly",
    ) -> ObjectiveDefinition:
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            constitutional_goal=constitutional_goal,
            description=description,
            scale_min=scale_min,
            scale_max=scale_max,
            cadence=cadence,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass
class ObjectiveReport:
    """A single self-reported objective measurement."""

    id: str
    objective_id: str
    value: float
    notes: str | None
    created_at: str

    @classmethod
    def create(
        cls,
        objective_id: str,
        value: float,
        notes: str | None = None,
    ) -> ObjectiveReport:
        return cls(
            id=str(uuid.uuid4()),
            objective_id=objective_id,
            value=value,
            notes=notes,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass
class QueryDecision:
    """Result of a VoI-based ask-vs-act decision."""

    should_ask: bool
    question: str | None
    dimension: str | None
    voi_score: float
    reasoning: str


@dataclass
class DriftReport:
    """Detected divergence between constitutional prior and learned posterior."""

    dimension: str
    context_key: str
    prior_mean: float
    posterior_mean: float
    shift_magnitude: float  # in standard deviations
    direction: str  # "increased" or "decreased"
    suggestion: str
