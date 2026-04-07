"""Work item and event models for hierarchical planning."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class WorkItemStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


# Valid transitions: {from_status: {allowed_to_statuses}}
VALID_TRANSITIONS: dict[WorkItemStatus, set[WorkItemStatus]] = {
    WorkItemStatus.PENDING: {WorkItemStatus.READY, WorkItemStatus.CANCELED},
    WorkItemStatus.READY: {WorkItemStatus.ACTIVE, WorkItemStatus.CANCELED},
    WorkItemStatus.ACTIVE: {
        WorkItemStatus.COMPLETED,
        WorkItemStatus.FAILED,
        WorkItemStatus.BLOCKED,
    },
    WorkItemStatus.BLOCKED: {WorkItemStatus.READY, WorkItemStatus.CANCELED},
    WorkItemStatus.FAILED: {WorkItemStatus.READY, WorkItemStatus.CANCELED},
    WorkItemStatus.COMPLETED: set(),
    WorkItemStatus.CANCELED: set(),
}


class CompletionMode(str, Enum):
    ALL = "all"
    ANY = "any"


class RollupMode(str, Enum):
    AUTO = "auto"
    SYNTHESIZE = "synthesize"


@dataclass
class WorkItem:
    id: str
    title: str
    description: str
    status: WorkItemStatus
    parent_id: str | None
    priority: int
    completion_mode: CompletionMode
    rollup_mode: RollupMode
    depends_on: list[str]
    context: dict[str, Any]
    result: str | None
    actor: str | None
    session_id: str | None
    max_attempts: int
    attempt_count: int
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        title: str,
        description: str = "",
        parent_id: str | None = None,
        priority: int = 0,
        completion_mode: CompletionMode = CompletionMode.ALL,
        rollup_mode: RollupMode = RollupMode.AUTO,
        depends_on: list[str] | None = None,
        context: dict[str, Any] | None = None,
        max_attempts: int = 3,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            status=WorkItemStatus.PENDING,
            parent_id=parent_id,
            priority=priority,
            completion_mode=completion_mode,
            rollup_mode=rollup_mode,
            depends_on=depends_on or [],
            context=context or {},
            result=None,
            actor=actor,
            session_id=session_id,
            max_attempts=max_attempts,
            attempt_count=0,
            reviewed_by=None,
            reviewed_at=None,
            created_at=now,
            updated_at=now,
        )


@dataclass
class WorkItemEvent:
    id: str
    item_id: str
    event_type: str  # created, status_changed, context_updated, result_set, etc.
    actor: str | None
    session_id: str | None
    data: dict[str, Any]
    created_at: str
    seq: int | None = None

    @classmethod
    def create(
        cls,
        item_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItemEvent:
        return cls(
            id=str(uuid.uuid4()),
            item_id=item_id,
            event_type=event_type,
            actor=actor,
            session_id=session_id,
            data=data or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
