"""Request API endpoints — human-in-the-loop protocol."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from cambium.server.auth import authenticate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/requests", tags=["requests"])


# --- Request/Response models ---


class CreateRequestRequest(BaseModel):
    type: str  # permission, information, preference
    summary: str
    detail: str = ""
    work_item_id: str | None = None
    options: list[str] | None = None
    default: str | None = None
    timeout_hours: float | None = None


class AnswerRequestRequest(BaseModel):
    answer: str


class RequestResponse(BaseModel):
    id: str
    session_id: str
    work_item_id: str | None
    type: str
    status: str
    summary: str
    detail: str
    options: list[str] | None
    default: str | None
    timeout_hours: float | None
    answer: str | None
    created_at: str
    answered_at: str | None
    created_by: str | None


class RequestSummary(BaseModel):
    counts: dict[str, dict[str, int]]


# --- Dependency injection ---

_service = None


def configure(service):
    """Called by app.py to inject dependencies."""
    global _service
    _service = service


def _get_service():
    if _service is None:
        raise HTTPException(status_code=503, detail="Request service not initialized")
    return _service


def _request_to_response(req) -> RequestResponse:
    return RequestResponse(
        id=req.id,
        session_id=req.session_id,
        work_item_id=req.work_item_id,
        type=req.type.value,
        status=req.status.value,
        summary=req.summary,
        detail=req.detail,
        options=req.options,
        default=req.default,
        timeout_hours=req.timeout_hours,
        answer=req.answer,
        created_at=req.created_at,
        answered_at=req.answered_at,
        created_by=req.created_by,
    )


# --- Endpoints ---


@router.post("", response_model=RequestResponse, status_code=201)
def create_request(
    body: CreateRequestRequest,
    authorization: str | None = Header(default=None),
):
    """Create a request for user input. Requires valid session token."""
    from cambium.request.model import RequestType

    service = _get_service()
    claims = authenticate(authorization)

    session_id = claims.get("session")
    if not session_id:
        raise HTTPException(
            status_code=403,
            detail="Only routines with an active session can create requests",
        )

    try:
        request_type = RequestType(body.type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request type: {body.type}. Must be one of: permission, information, preference",
        )

    request = service.create_request(
        session_id=session_id,
        type=request_type,
        summary=body.summary,
        detail=body.detail,
        work_item_id=body.work_item_id,
        options=body.options,
        default=body.default,
        timeout_hours=body.timeout_hours,
        created_by=claims["routine"],
    )
    return _request_to_response(request)


# Routines permitted to answer/reject requests on behalf of the human.
# - "interlocutor": the chat routine the human talks through
# - "human": the UI (direct human action, token minted at server startup)
_HUMAN_ROUTINES = {"interlocutor", "human"}


@router.post("/{request_id}/answer", response_model=RequestResponse)
def answer_request(
    request_id: str,
    body: AnswerRequestRequest,
    authorization: str | None = Header(default=None),
):
    """Answer a pending request. Only the interlocutor or UI can answer."""
    service = _get_service()
    claims = authenticate(authorization)

    if claims.get("routine") not in _HUMAN_ROUTINES:
        raise HTTPException(
            status_code=403,
            detail="Only the interlocutor or UI can answer requests",
        )

    try:
        request = service.answer_request(request_id, body.answer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _request_to_response(request)


@router.post("/{request_id}/reject")
def reject_request(
    request_id: str,
    authorization: str | None = Header(default=None),
):
    """Reject a pending request. Only the interlocutor or UI can reject."""
    service = _get_service()
    claims = authenticate(authorization)

    if claims.get("routine") not in _HUMAN_ROUTINES:
        raise HTTPException(
            status_code=403,
            detail="Only the interlocutor or UI can reject requests",
        )

    try:
        service.reject_request(request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "rejected"}


class SeedRequestRequest(BaseModel):
    """Seed a request directly — no auth required. For eval staging only."""
    type: str
    summary: str
    detail: str = ""
    options: list[str] | None = None
    default: str | None = None
    timeout_hours: float | None = None
    session_id: str = "seed-session"
    created_by: str = "seed"


@router.post("/seed", response_model=RequestResponse, status_code=201)
def seed_request(body: SeedRequestRequest):
    """Seed a request without authentication. For eval/test staging."""
    from cambium.request.model import RequestType

    service = _get_service()
    try:
        request_type = RequestType(body.type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request type: {body.type}",
        )

    request = service.create_request(
        session_id=body.session_id,
        type=request_type,
        summary=body.summary,
        detail=body.detail,
        options=body.options,
        default=body.default,
        timeout_hours=body.timeout_hours,
        created_by=body.created_by,
    )
    return _request_to_response(request)


@router.get("/summary", response_model=RequestSummary)
def get_summary():
    """Get request counts by type and status."""
    service = _get_service()
    return RequestSummary(counts=service.get_summary())


@router.get("/{request_id}", response_model=RequestResponse)
def get_request(request_id: str):
    """Get a single request by ID."""
    service = _get_service()
    request = service.get_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return _request_to_response(request)


@router.get("", response_model=list[RequestResponse])
def list_requests(
    status: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
):
    """List requests with optional filters."""
    from cambium.request.model import RequestStatus

    service = _get_service()
    status_filter = RequestStatus(status) if status else None
    requests = service.store.list_requests(
        status=status_filter, session_id=session_id, limit=limit,
    )
    return [_request_to_response(r) for r in requests]
