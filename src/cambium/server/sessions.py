"""Session API endpoints — OpenAI-compatible streaming interface."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cambium.models.message import Message
from cambium.session.model import Session, SessionOrigin, SessionStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# --- Request/Response models ---


class CreateSessionRequest(BaseModel):
    routine_name: str
    adapter_instance_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    id: str
    origin: str
    status: str
    routine_name: str | None
    adapter_instance_name: str | None
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


class Attachment(BaseModel):
    """A file attachment on a message."""
    data_url: str             # base64 data URL (data:<media_type>;base64,...)
    name: str | None = None   # original filename; auto-generated if absent


class SendMessageRequest(BaseModel):
    """OpenAI-compatible message request (simplified)."""
    messages: list[dict[str, Any]]
    images: list[str] | None = None         # base64 data URLs (legacy, images only)
    attachments: list[Attachment] | None = None  # general-purpose file attachments
    stream: bool = True


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    sequence: int


# --- Dependency injection ---
# These are set by the server app at startup.

_session_store = None
_broadcaster_registry = None
_routine_registry = None
_routine_runner = None
_queue = None


def configure(session_store, broadcaster_registry, routine_registry, routine_runner, queue=None):
    """Called by app.py to inject dependencies."""
    global _session_store, _broadcaster_registry, _routine_registry, _routine_runner, _queue
    _session_store = session_store
    _broadcaster_registry = broadcaster_registry
    _routine_registry = routine_registry
    _routine_runner = routine_runner
    _queue = queue


def _get_deps():
    if _session_store is None:
        raise HTTPException(status_code=503, detail="Session service not initialized")
    return _session_store, _broadcaster_registry, _routine_registry, _routine_runner


# --- Endpoints ---


@router.get("", response_model=list[SessionResponse])
def list_sessions(origin: str | None = None, status: str | None = None, limit: int = 50):
    """List sessions, optionally filtered by origin and/or status."""
    store, _, _, _ = _get_deps()

    origin_filter = SessionOrigin(origin) if origin else None
    status_filter = SessionStatus(status) if status else None

    sessions = store.list_sessions(origin=origin_filter, status=status_filter, limit=limit)
    return [_session_to_response(s) for s in sessions]


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(body: CreateSessionRequest):
    """Create an interactive session."""
    store, _, routine_reg, _ = _get_deps()

    routine = routine_reg.get(body.routine_name)
    if routine is None:
        raise HTTPException(status_code=404, detail=f"Routine not found: {body.routine_name}")

    adapter_instance_name = body.adapter_instance_name or routine.adapter_instance

    session = Session.create(
        origin=SessionOrigin.USER,
        routine_name=body.routine_name,
        adapter_instance_name=adapter_instance_name,
        metadata=body.metadata,
    )
    store.create_session(session)

    log.info(f"Created user session {session.id[:8]} for routine '{body.routine_name}'")
    return _session_to_response(session)


@router.post("/{session_id}/messages")
async def send_message(session_id: str, body: SendMessageRequest):
    """Send a message and get a streaming SSE response (OpenAI-compatible)."""
    store, broadcaster_reg, routine_reg, runner = _get_deps()

    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    # Completed/failed sessions can be reopened — the runner reactivates them

    routine = routine_reg.get(session.routine_name)
    if routine is None:
        raise HTTPException(status_code=404, detail=f"Routine not found: {session.routine_name}")

    # Extract the last user message
    user_messages = [m for m in body.messages if m.get("role") == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message provided")
    user_content = user_messages[-1].get("content", "")

    # Merge legacy `images` field and new `attachments` field into a
    # unified list of (data_url, name|None) tuples for the runner.
    all_attachments: list[tuple[str, str | None]] = []
    for url in (body.images or []):
        all_attachments.append((url, None))
    for att in (body.attachments or []):
        all_attachments.append((att.data_url, att.name))

    # Separate image data URLs (for inline vision) from all attachments
    image_data_urls = [url for url, _ in all_attachments if url.startswith("data:image/")]

    # Create broadcaster for this invocation
    broadcaster = broadcaster_reg.create(session_id)

    # Run adapter via the runner in a background thread
    async def run_adapter():
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: runner.send_message(
                    routine=routine,
                    session_id=session_id,
                    user_message=user_content,
                    images=image_data_urls if image_data_urls else None,
                    attachments=all_attachments if all_attachments else None,
                    live=True,
                    on_event=lambda chunk: broadcaster.publish(chunk),
                ),
            )
            if not result.success:
                log.error(f"Session {session_id[:8]} failed: {result.error}")
        except Exception:
            log.exception(f"Session {session_id[:8]} adapter error")
        finally:
            broadcaster.close()
            broadcaster_reg.remove(session_id)

    # Start adapter in background
    asyncio.create_task(run_adapter())

    if not body.stream:
        # Non-streaming: wait for completion and return final message
        # For now, just return 202 — full non-streaming support is a future enhancement
        raise HTTPException(status_code=501, detail="Non-streaming mode not yet supported")

    # Stream SSE response
    async def event_stream():
        async for chunk in broadcaster.subscribe():
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
def get_messages(session_id: str, after: int = -1, limit: int = 100):
    """Get conversation history for a session."""
    store, _, _, _ = _get_deps()

    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = store.get_messages(session_id, after_sequence=after, limit=limit)
    return [
        MessageResponse(
            id=m.id, role=m.role, content=m.content,
            created_at=m.created_at, sequence=m.sequence,
        )
        for m in messages
    ]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    """Get session metadata."""
    store, _, _, _ = _get_deps()

    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return _session_to_response(session)


@router.get("/{session_id}/stream")
async def stream_session(session_id: str):
    """Observe a running session via SSE. For one-shot sessions triggered by the consumer."""
    store, broadcaster_reg, _, _ = _get_deps()

    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    broadcaster = broadcaster_reg.get(session_id)
    if broadcaster is None:
        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            # Session is done, replay stored messages as a single response
            messages = store.get_messages(session_id)
            async def replay():
                for m in messages:
                    if m.role == "assistant":
                        chunk = {
                            "id": f"chatcmpl-{session_id[:12]}",
                            "object": "chat.completion.chunk",
                            "created": 0,
                            "model": "unknown",
                            "choices": [{"index": 0, "delta": {"content": m.content}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(replay(), media_type="text/event-stream")
        raise HTTPException(status_code=404, detail="No active stream for this session")

    async def event_stream():
        async for chunk in broadcaster.subscribe():
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{session_id}/metadata", response_model=SessionResponse)
def update_metadata(session_id: str, body: dict[str, Any]):
    """Merge keys into session metadata."""
    store, _, _, _ = _get_deps()

    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    store.update_metadata(session_id, body)

    updated = store.get_session(session_id)
    return _session_to_response(updated)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str):
    """End a session."""
    store, broadcaster_reg, _, _ = _get_deps()

    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    store.update_status(session_id, SessionStatus.COMPLETED)

    broadcaster = broadcaster_reg.get(session_id)
    if broadcaster:
        broadcaster.close()
        broadcaster_reg.remove(session_id)

    # Notify downstream routines (e.g., session-summarizer) that
    # the interactive session is now finished — but only if there
    # are actual messages to summarize.
    has_messages = store.get_messages(session_id, limit=1)
    if _queue and has_messages:
        _queue.publish(Message.create(
            channel="sessions_completed",
            payload={
                "session_id": session_id,
                "routine_name": session.routine_name,
                "success": True,
                "trigger_channel": "user",
            },
            source="system",
        ))

    log.info(f"Session {session_id[:8]} ended")


def _session_to_response(session: Session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        origin=session.origin.value,
        status=session.status.value,
        routine_name=session.routine_name,
        adapter_instance_name=session.adapter_instance_name,
        created_at=session.created_at,
        updated_at=session.updated_at,
        metadata=session.metadata,
    )
