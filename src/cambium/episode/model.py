"""Episodic memory models — episodes (routine invocations) and channel events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EpisodeStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Episode:
    """A single routine invocation — one row in the episodic timeline."""

    id: str
    session_id: str
    routine: str
    started_at: str
    ended_at: str | None
    status: EpisodeStatus
    trigger_event_ids: list[str]
    emitted_event_ids: list[str]
    session_acknowledged: bool
    session_summary: str | None
    summarizer_acknowledged: bool
    digest_path: str | None

    @classmethod
    def create(
        cls,
        session_id: str,
        routine: str,
        trigger_event_ids: list[str] | None = None,
    ) -> Episode:
        return cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            routine=routine,
            started_at=datetime.now(timezone.utc).isoformat(),
            ended_at=None,
            status=EpisodeStatus.RUNNING,
            trigger_event_ids=trigger_event_ids or [],
            emitted_event_ids=[],
            session_acknowledged=False,
            session_summary=None,
            summarizer_acknowledged=False,
            digest_path=None,
        )


@dataclass
class ChannelEvent:
    """A message published to a channel — immutable audit log entry."""

    id: str
    timestamp: str
    channel: str
    source_session_id: str | None
    payload: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        channel: str,
        payload: dict | None = None,
        source_session_id: str | None = None,
    ) -> ChannelEvent:
        return cls(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            channel=channel,
            source_session_id=source_session_id,
            payload=payload or {},
        )
