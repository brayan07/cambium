"""Message data model — the unit of communication in Cambium's channel-based pub/sub."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Message:
    """A message published to a channel."""

    id: str
    channel: str
    payload: dict
    source: str  # routine that published this
    timestamp: datetime
    status: str = "pending"
    attempts: int = 0
    claimed_at: datetime | None = None

    @classmethod
    def create(cls, channel: str, payload: dict, source: str) -> Message:
        return cls(
            id=str(uuid.uuid4()),
            channel=channel,
            payload=payload,
            source=source,
            timestamp=datetime.now(timezone.utc),
        )
