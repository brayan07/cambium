"""Work item API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from cambium.server.auth import authenticate
from cambium.work_item.model import CompletionMode, RollupMode, WorkItemStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/work-items", tags=["work-items"])


# --- Request/Response models ---


class CreateWorkItemRequest(BaseModel):
    title: str
    description: str = ""
    parent_id: str | None = None
    priority: int = 0
    completion_mode: str = "all"
    rollup_mode: str = "auto"
    depends_on: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 3


class ChildSpec(BaseModel):
    title: str
    description: str = ""
    priority: int = 0
    depends_on: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 3


class DecomposeRequest(BaseModel):
    children: list[ChildSpec]


class CompleteRequest(BaseModel):
    result: str


class FailRequest(BaseModel):
    error: str


class ReviewRequest(BaseModel):
    verdict: str  # "accepted" or "rejected"
    feedback: str = ""


class BlockRequest(BaseModel):
    reason: str = ""


class WorkItemResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    parent_id: str | None
    priority: int
    completion_mode: str
    rollup_mode: str
    depends_on: list[str]
    context: dict[str, Any]
    result: str | None
    actor: str | None
    session_id: str | None
    max_attempts: int
    attempt_count: int
    created_at: str
    updated_at: str


class DecomposeResponse(BaseModel):
    parent: WorkItemResponse
    children: list[WorkItemResponse]


class EventResponse(BaseModel):
    id: str
    item_id: str
    event_type: str
    actor: str | None
    session_id: str | None
    data: dict[str, Any]
    created_at: str


# --- Dependency injection ---

_service = None


def configure(service):
    """Called by app.py to inject dependencies."""
    global _service
    _service = service


def _get_service():
    if _service is None:
        raise HTTPException(status_code=503, detail="Work item service not initialized")
    return _service


def _extract_identity(authorization: str | None) -> tuple[str | None, str | None]:
    """Extract actor and session_id from JWT if present."""
    if not authorization:
        return None, None
    try:
        claims = authenticate(authorization)
        return claims.get("routine"), claims.get("session")
    except HTTPException:
        return None, None


def _item_to_response(item) -> WorkItemResponse:
    return WorkItemResponse(
        id=item.id,
        title=item.title,
        description=item.description,
        status=item.status.value,
        parent_id=item.parent_id,
        priority=item.priority,
        completion_mode=item.completion_mode.value,
        rollup_mode=item.rollup_mode.value,
        depends_on=item.depends_on,
        context=item.context,
        result=item.result,
        actor=item.actor,
        session_id=item.session_id,
        max_attempts=item.max_attempts,
        attempt_count=item.attempt_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _event_to_response(event) -> EventResponse:
    return EventResponse(
        id=event.id,
        item_id=event.item_id,
        event_type=event.event_type,
        actor=event.actor,
        session_id=event.session_id,
        data=event.data,
        created_at=event.created_at,
    )


# --- Endpoints ---


@router.post("", response_model=WorkItemResponse, status_code=201)
def create_work_item(
    body: CreateWorkItemRequest,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    item = service.create_item(
        title=body.title,
        description=body.description,
        parent_id=body.parent_id,
        priority=body.priority,
        completion_mode=CompletionMode(body.completion_mode),
        rollup_mode=RollupMode(body.rollup_mode),
        depends_on=body.depends_on,
        context=body.context,
        max_attempts=body.max_attempts,
        actor=actor,
        session_id=session_id,
    )
    return _item_to_response(item)


@router.post("/{item_id}/decompose", response_model=DecomposeResponse)
def decompose_work_item(
    item_id: str,
    body: DecomposeRequest,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    try:
        parent, children = service.decompose(
            parent_id=item_id,
            children_specs=[c.model_dump() for c in body.children],
            actor=actor,
            session_id=session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DecomposeResponse(
        parent=_item_to_response(service.store.get(parent.id)),
        children=[_item_to_response(c) for c in children],
    )


@router.post("/{item_id}/claim", response_model=WorkItemResponse)
def claim_work_item(
    item_id: str,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    if not actor or not session_id:
        raise HTTPException(status_code=401, detail="Authentication required to claim")
    claimed = service.claim_item(item_id, session_id=session_id, actor=actor)
    if claimed is None:
        raise HTTPException(status_code=409, detail="Item not available for claiming")
    return _item_to_response(claimed)


@router.post("/{item_id}/complete", response_model=WorkItemResponse)
def complete_work_item(
    item_id: str,
    body: CompleteRequest,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    try:
        item = service.complete_item(
            item_id, result=body.result, actor=actor, session_id=session_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _item_to_response(item)


@router.post("/{item_id}/fail", response_model=WorkItemResponse)
def fail_work_item(
    item_id: str,
    body: FailRequest,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    try:
        item = service.fail_item(
            item_id, error=body.error, actor=actor, session_id=session_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _item_to_response(item)


@router.post("/{item_id}/review", response_model=WorkItemResponse)
def review_work_item(
    item_id: str,
    body: ReviewRequest,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    try:
        item = service.review_item(
            item_id,
            verdict=body.verdict,
            feedback=body.feedback,
            actor=actor,
            session_id=session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _item_to_response(item)


@router.post("/{item_id}/block", response_model=WorkItemResponse)
def block_work_item(
    item_id: str,
    body: BlockRequest,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    try:
        item = service.block_item(
            item_id, reason=body.reason, actor=actor, session_id=session_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _item_to_response(item)


@router.post("/{item_id}/unblock", response_model=WorkItemResponse)
def unblock_work_item(
    item_id: str,
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    try:
        item = service.unblock_item(
            item_id, actor=actor, session_id=session_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _item_to_response(item)


@router.patch("/{item_id}/context", response_model=WorkItemResponse)
def update_context(
    item_id: str,
    body: dict[str, Any],
    authorization: str | None = Header(default=None),
):
    service = _get_service()
    actor, session_id = _extract_identity(authorization)
    item = service.store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    service.store.update_context(item_id, body, actor=actor, session_id=session_id)
    return _item_to_response(service.store.get(item_id))


@router.get("/{item_id}", response_model=WorkItemResponse)
def get_work_item(item_id: str):
    service = _get_service()
    item = service.store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return _item_to_response(item)


@router.get("/{item_id}/children", response_model=list[WorkItemResponse])
def get_children(item_id: str):
    service = _get_service()
    children = service.store.get_children(item_id)
    return [_item_to_response(c) for c in children]


@router.get("/{item_id}/tree", response_model=list[WorkItemResponse])
def get_tree(item_id: str):
    service = _get_service()
    items = service.store.get_subtree(item_id)
    return [_item_to_response(i) for i in items]


@router.get("", response_model=list[WorkItemResponse])
def list_work_items(
    status: str | None = None,
    parent_id: str | None = None,
    limit: int = 50,
):
    service = _get_service()
    status_filter = WorkItemStatus(status) if status else None
    items = service.store.list_items(status=status_filter, parent_id=parent_id, limit=limit)
    return [_item_to_response(i) for i in items]


@router.get("/{item_id}/events", response_model=list[EventResponse])
def get_item_events(item_id: str, event_type: str | None = None, limit: int = 100):
    service = _get_service()
    events = service.store.get_events(item_id=item_id, event_type=event_type, limit=limit)
    return [_event_to_response(e) for e in events]


@router.get("/events/all", response_model=list[EventResponse])
def get_all_events(
    event_type: str | None = None,
    after: str | None = None,
    limit: int = 100,
):
    service = _get_service()
    events = service.store.get_events(event_type=event_type, after=after, limit=limit)
    return [_event_to_response(e) for e in events]
