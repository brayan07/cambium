"""Metric API endpoints — metric definitions and time-series readings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from cambium.server.auth import authenticate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# --- Request/Response models ---


class RecordReadingRequest(BaseModel):
    value: float
    detail: str = ""
    source: str = "api"


class SeedReadingRequest(BaseModel):
    metric_name: str
    value: float
    detail: str = ""
    source: str = "seed"
    recorded_at: str | None = None


class ReadingResponse(BaseModel):
    id: str
    metric_name: str
    value: float
    detail: str
    source: str
    recorded_at: str


class MetricResponse(BaseModel):
    name: str
    type: str
    description: str
    unit: str
    tags: list[str]
    schedule: str


class MetricSummaryResponse(BaseModel):
    metric_name: str
    min: float | None
    max: float | None
    avg: float | None
    count: int
    latest_value: float | None
    latest_at: str | None


# --- Dependency injection ---

_service = None


def configure(service):
    """Called by app.py to inject dependencies."""
    global _service
    _service = service


def _get_service():
    if _service is None:
        raise HTTPException(status_code=503, detail="Metric service not initialized")
    return _service


def _metric_to_response(m) -> MetricResponse:
    return MetricResponse(
        name=m.name,
        type=m.type.value,
        description=m.description,
        unit=m.unit,
        tags=m.tags,
        schedule=m.schedule,
    )


def _reading_to_response(r) -> ReadingResponse:
    return ReadingResponse(
        id=r.id,
        metric_name=r.metric_name,
        value=r.value,
        detail=r.detail,
        source=r.source,
        recorded_at=r.recorded_at,
    )


# --- Endpoints ---


@router.get("", response_model=list[MetricResponse])
def list_metrics(
    type: str | None = Query(None),
    tag: str | None = Query(None),
    authorization: str = Header(None),
):
    authenticate(authorization)
    service = _get_service()
    metrics = service.get_metrics(type=type, tag=tag)
    return [_metric_to_response(m) for m in metrics]


@router.get("/{name}", response_model=MetricResponse)
def get_metric(name: str, authorization: str = Header(None)):
    authenticate(authorization)
    service = _get_service()
    metric = service.get_metric(name)
    if metric is None:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found")
    return _metric_to_response(metric)


@router.get("/{name}/readings", response_model=list[ReadingResponse])
def list_readings(
    name: str,
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    authorization: str = Header(None),
):
    authenticate(authorization)
    service = _get_service()
    if service.get_metric(name) is None:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found")
    readings = service.list_readings(name, since=since, until=until, limit=limit)
    return [_reading_to_response(r) for r in readings]


@router.post("/{name}/readings", response_model=ReadingResponse, status_code=201)
def record_reading(
    name: str,
    body: RecordReadingRequest,
    authorization: str = Header(None),
):
    authenticate(authorization)
    service = _get_service()
    if service.get_metric(name) is None:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found")
    reading = service.record_reading(
        metric_name=name,
        value=body.value,
        detail=body.detail,
        source=body.source,
    )
    return _reading_to_response(reading)


@router.get("/{name}/summary", response_model=MetricSummaryResponse)
def get_summary(
    name: str,
    since: str | None = Query(None),
    until: str | None = Query(None),
    authorization: str = Header(None),
):
    authenticate(authorization)
    service = _get_service()
    if service.get_metric(name) is None:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found")
    summary = service.get_summary(name, since=since, until=until)
    return MetricSummaryResponse(**summary)


@router.post("/seed", response_model=list[ReadingResponse], status_code=201)
def seed_readings(body: list[SeedReadingRequest]):
    """Bulk-seed readings for eval scaffolding. Unauthenticated."""
    service = _get_service()
    from cambium.metric.model import Reading

    results = []
    for sr in body:
        if service.get_metric(sr.metric_name) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Metric '{sr.metric_name}' not found",
            )
        reading = Reading.create(
            metric_name=sr.metric_name,
            value=sr.value,
            detail=sr.detail,
            source=sr.source,
        )
        if sr.recorded_at:
            reading.recorded_at = sr.recorded_at
        service.store.record_reading(reading)
        results.append(_reading_to_response(reading))
    return results
