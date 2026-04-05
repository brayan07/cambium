"""Session and message models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class TranscriptEvent:
    """Adapter-agnostic transcript event for persistence.

    Each adapter translates its native events into this shape. The runner
    persists these blindly — it never inspects ``raw`` or parses ``content``.
    """

    role: str  # assistant, user, system, tool, etc.
    content: str  # human-readable summary (adapter-produced)
    event_type: str  # adapter-specific type label (e.g. "assistant", "system")
    raw: dict = field(default_factory=dict)  # full original event, opaque to runner


class SessionType(str, Enum):
    ONE_SHOT = "one_shot"
    INTERACTIVE = "interactive"


class SessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Session:
    id: str
    type: SessionType
    status: SessionStatus
    routine_name: str | None = None
    adapter_instance_name: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        session_type: SessionType,
        routine_name: str | None = None,
        adapter_instance_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=str(uuid.uuid4()),
            type=session_type,
            status=SessionStatus.CREATED,
            routine_name=routine_name,
            adapter_instance_name=adapter_instance_name,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )


@dataclass
class SessionMessage:
    id: str
    session_id: str
    role: str  # user, assistant, system, tool
    content: str
    created_at: str = ""
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        session_id: str,
        role: str,
        content: str,
        sequence: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        return cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
            sequence=sequence,
            metadata=metadata or {},
        )
