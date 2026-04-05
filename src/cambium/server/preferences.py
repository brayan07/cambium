"""Preference learning API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/preferences", tags=["preferences"])

_service = None
_work_item_store = None


def configure(service, work_item_store=None):
    """Called by app.py to inject dependencies."""
    global _service, _work_item_store
    _service = service
    _work_item_store = work_item_store


def _get_service():
    if _service is None:
        raise HTTPException(status_code=503, detail="Preference service not initialized")
    return _service


def _get_work_item(item_id: str):
    if _work_item_store is None:
        raise HTTPException(status_code=503, detail="Work item store not configured")
    item = _work_item_store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return item


# --- Request/Response models ---


class DimensionResponse(BaseModel):
    id: str
    name: str
    description: str
    anchors: dict[str, str]
    constitutional_source: str | None


class DimensionStateResponse(BaseModel):
    dimension_id: str
    context_key: str
    mean: float
    variance: float
    update_count: int
    confidence_pct: int


class SignalResponse(BaseModel):
    id: str
    dimension_id: str
    context_key: str
    signal_type: str
    signal_value: float
    observation_variance: float
    prior_mean: float
    posterior_mean: float
    source_item_id: str | None
    created_at: str


class CaseResponse(BaseModel):
    id: str
    work_item_id: str
    domain: str
    task_type: str
    lesson: str
    signal_direction: float
    feedback: str | None
    retrieval_count: int
    usefulness_score: float
    created_at: str


class CreateCaseRequest(BaseModel):
    work_item_id: str
    lesson: str
    verdict: str = "accepted"
    feedback: str = ""


class ObjectiveResponse(BaseModel):
    id: str
    name: str
    constitutional_goal: str
    description: str
    scale_min: float
    scale_max: float
    cadence: str


class ObjectiveReportRequest(BaseModel):
    value: float
    notes: str | None = None


class ObjectiveReportResponse(BaseModel):
    id: str
    objective_id: str
    value: float
    notes: str | None
    created_at: str


class PreferenceContextResponse(BaseModel):
    dimensions: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    prompt_text: str


# --- Endpoints ---


@router.get("/context/{work_item_id}", response_model=PreferenceContextResponse)
def get_preference_context(work_item_id: str):
    """Returns preference dimensions, cases, and prompt text for a work item."""
    service = _get_service()
    item = _get_work_item(work_item_id)
    context = service.build_preference_context(item)
    return PreferenceContextResponse(**context)


@router.get("/dimensions", response_model=list[DimensionResponse])
def list_dimensions():
    service = _get_service()
    dims = service.store.list_dimensions()
    return [DimensionResponse(
        id=d.id, name=d.name, description=d.description,
        anchors=d.anchors, constitutional_source=d.constitutional_source,
    ) for d in dims]


@router.get("/dimensions/{name}/state", response_model=DimensionStateResponse)
def get_dimension_state(name: str, context_key: str = "global"):
    service = _get_service()
    dim = service.store.get_dimension_by_name(name)
    if dim is None:
        raise HTTPException(status_code=404, detail=f"Dimension '{name}' not found")
    state = service.store.get_state(dim.id, context_key)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No state for context '{context_key}'")
    return DimensionStateResponse(
        dimension_id=state.dimension_id, context_key=state.context_key,
        mean=round(state.mean, 4), variance=round(state.variance, 5),
        update_count=state.update_count,
        confidence_pct=max(0, min(99, int(100 * (1.0 - state.variance * 3.0)))),
    )


@router.get("/signals", response_model=list[SignalResponse])
def list_signals(
    dimension: str | None = None,
    source_item_id: str | None = None,
    limit: int = 100,
):
    service = _get_service()
    dim_id = None
    if dimension:
        dim = service.store.get_dimension_by_name(dimension)
        if dim is None:
            raise HTTPException(status_code=404, detail=f"Dimension '{dimension}' not found")
        dim_id = dim.id
    signals = service.store.get_signals(dimension_id=dim_id, source_item_id=source_item_id, limit=limit)
    return [SignalResponse(
        id=s.id, dimension_id=s.dimension_id, context_key=s.context_key,
        signal_type=s.signal_type, signal_value=s.signal_value,
        observation_variance=s.observation_variance,
        prior_mean=round(s.prior_mean, 4), posterior_mean=round(s.posterior_mean, 4),
        source_item_id=s.source_item_id, created_at=s.created_at,
    ) for s in signals]


@router.post("/cases", response_model=CaseResponse, status_code=201)
def create_case(body: CreateCaseRequest):
    """Create a case from a reviewed work item (typically called by the consolidator)."""
    service = _get_service()
    item = _get_work_item(body.work_item_id)
    case = service.create_case_from_review(item, body.verdict, body.feedback, body.lesson)
    return _case_to_response(case)


@router.get("/cases", response_model=list[CaseResponse])
def list_cases(domain: str | None = None, task_type: str | None = None, limit: int = 20):
    service = _get_service()
    cases = service.store.query_cases(domain=domain, task_type=task_type, limit=limit)
    return [_case_to_response(c) for c in cases]


@router.get("/objectives", response_model=list[ObjectiveResponse])
def list_objectives():
    service = _get_service()
    objs = service.store.list_objectives()
    return [ObjectiveResponse(
        id=o.id, name=o.name, constitutional_goal=o.constitutional_goal,
        description=o.description, scale_min=o.scale_min, scale_max=o.scale_max,
        cadence=o.cadence,
    ) for o in objs]


@router.post("/objectives/{name}/report", response_model=ObjectiveReportResponse, status_code=201)
def record_objective(name: str, body: ObjectiveReportRequest):
    service = _get_service()
    try:
        report = service.record_objective(name, body.value, body.notes)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ObjectiveReportResponse(
        id=report.id, objective_id=report.objective_id,
        value=report.value, notes=report.notes, created_at=report.created_at,
    )


@router.get("/objectives/{name}/reports", response_model=list[ObjectiveReportResponse])
def get_objective_reports(name: str, limit: int = 50):
    service = _get_service()
    obj = service.store.get_objective_by_name(name)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"Objective '{name}' not found")
    reports = service.store.get_objective_reports(obj.id, limit=limit)
    return [ObjectiveReportResponse(
        id=r.id, objective_id=r.objective_id,
        value=r.value, notes=r.notes, created_at=r.created_at,
    ) for r in reports]


def _case_to_response(c) -> CaseResponse:
    return CaseResponse(
        id=c.id, work_item_id=c.work_item_id, domain=c.domain,
        task_type=c.task_type, lesson=c.lesson,
        signal_direction=c.signal_direction, feedback=c.feedback,
        retrieval_count=c.retrieval_count, usefulness_score=c.usefulness_score,
        created_at=c.created_at,
    )
