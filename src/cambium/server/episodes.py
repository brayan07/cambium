"""Episodic memory API — query the timeline of routine invocations and channel events."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from cambium.episode.store import EpisodeStore
from cambium.server.auth import verify_session_token

router = APIRouter(tags=["episodes"])

# --- Module-level dependency injection ---

_episode_store: EpisodeStore | None = None


def configure(episode_store: EpisodeStore) -> None:
    global _episode_store
    _episode_store = episode_store


def _get_store() -> EpisodeStore:
    if _episode_store is None:
        raise HTTPException(status_code=503, detail="Episode store not initialized")
    return _episode_store


# --- Pydantic models ---


class EpisodeResponse(BaseModel):
    id: str
    session_id: str
    routine: str
    started_at: str
    ended_at: str | None
    status: str
    trigger_event_ids: list[str]
    emitted_event_ids: list[str]
    session_acknowledged: bool
    session_summary: str | None
    summarizer_acknowledged: bool
    digest_path: str | None


class EventResponse(BaseModel):
    id: str
    timestamp: str
    channel: str
    source_session_id: str | None
    payload: dict


class SummaryRequest(BaseModel):
    summary: str


class SummarizerAckRequest(BaseModel):
    session_id: str
    digest_path: str


# --- Helpers ---


def _episode_to_response(ep) -> EpisodeResponse:
    return EpisodeResponse(
        id=ep.id,
        session_id=ep.session_id,
        routine=ep.routine,
        started_at=ep.started_at,
        ended_at=ep.ended_at,
        status=ep.status.value,
        trigger_event_ids=ep.trigger_event_ids,
        emitted_event_ids=ep.emitted_event_ids,
        session_acknowledged=ep.session_acknowledged,
        session_summary=ep.session_summary,
        summarizer_acknowledged=ep.summarizer_acknowledged,
        digest_path=ep.digest_path,
    )


def _event_to_response(ev) -> EventResponse:
    return EventResponse(
        id=ev.id,
        timestamp=ev.timestamp,
        channel=ev.channel,
        source_session_id=ev.source_session_id,
        payload=ev.payload,
    )


# --- Episode endpoints ---


@router.get("/episodes", response_model=list[EpisodeResponse])
def list_episodes(
    since: str = Query(..., description="ISO timestamp lower bound (required)"),
    until: str = Query(..., description="ISO timestamp upper bound (required)"),
    routine: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    store = _get_store()
    episodes = store.list_episodes(since=since, until=until, routine=routine, limit=limit)
    return [_episode_to_response(ep) for ep in episodes]


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
def get_episode(episode_id: str):
    store = _get_store()
    ep = store.get_episode(episode_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return _episode_to_response(ep)


@router.post("/episodes/summary", response_model=EpisodeResponse)
def post_summary(
    body: SummaryRequest,
    authorization: str | None = Header(default=None),
):
    """Session posts its own summary. Requires JWT auth."""
    store = _get_store()

    if authorization is None:
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization.removeprefix("Bearer ").strip()
    claims = verify_session_token(token)
    session_id = claims.get("session")
    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid session token")

    ep = store.get_episode_by_session(session_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="No episode found for this session")

    store.acknowledge_session(session_id, body.summary)
    return _episode_to_response(store.get_episode(ep.id))


@router.post("/episodes/summarizer-ack", response_model=EpisodeResponse)
def post_summarizer_ack(
    body: SummarizerAckRequest,
    authorization: str | None = Header(default=None),
):
    """Mark an episode as acknowledged by the summarizer, with digest path."""
    store = _get_store()

    if authorization is None:
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization.removeprefix("Bearer ").strip()
    verify_session_token(token)

    ep = store.get_episode_by_session(body.session_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="No episode found for this session")

    store.acknowledge_summarizer(body.session_id, body.digest_path)
    return _episode_to_response(store.get_episode(ep.id))


# --- Event endpoints ---


@router.get("/events", response_model=list[EventResponse])
def list_events(
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    store = _get_store()
    events = store.list_events(since=since, until=until, channel=channel, limit=limit)
    return [_event_to_response(ev) for ev in events]


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: str):
    store = _get_store()
    ev = store.get_event(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_to_response(ev)
