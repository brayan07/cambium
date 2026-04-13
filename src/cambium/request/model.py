"""Request model for human-in-the-loop protocol."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class RequestType(str, Enum):
    PERMISSION = "permission"
    INFORMATION = "information"
    PREFERENCE = "preference"
    SURVEY = "survey"


class RequestStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass
class Request:
    id: str
    session_id: str | None
    work_item_id: str | None
    type: RequestType
    status: RequestStatus
    summary: str
    detail: str
    options: list[str] | None
    default: str | None
    timeout_hours: float | None
    answer: str | None
    created_at: str
    answered_at: str | None
    created_by: str | None

    @classmethod
    def create(
        cls,
        session_id: str | None,
        type: RequestType,
        summary: str,
        detail: str = "",
        work_item_id: str | None = None,
        options: list[str] | None = None,
        default: str | None = None,
        timeout_hours: float | None = None,
        created_by: str | None = None,
    ) -> Request:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            work_item_id=work_item_id,
            type=type,
            status=RequestStatus.PENDING,
            summary=summary,
            detail=detail,
            options=options,
            default=default,
            timeout_hours=timeout_hours,
            answer=None,
            created_at=now,
            answered_at=None,
            created_by=created_by,
        )
