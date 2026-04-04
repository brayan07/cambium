"""Event data model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Event:
    """An event flowing through the Cambium queue."""

    id: str
    type: str
    payload: dict
    source: str
    timestamp: datetime
    status: str = "pending"
    attempts: int = 0
    claimed_at: datetime | None = None

    @classmethod
    def create(cls, type: str, payload: dict, source: str) -> Event:
        """Factory for creating a new event with auto-generated id and timestamp."""
        return cls(
            id=str(uuid.uuid4()),
            type=type,
            payload=payload,
            source=source,
            timestamp=datetime.now(timezone.utc),
        )
