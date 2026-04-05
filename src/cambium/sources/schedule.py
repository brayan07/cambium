"""Schedule source — emits periodic events to trigger time-based routines.

Replaces n8n's cron-based triggers (e.g., the 30-minute grooming sweep).
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from cambium.models.message import Message
from cambium.queue.base import QueueAdapter
from cambium.sources.base import EventSource

log = logging.getLogger(__name__)


class ScheduleSource(EventSource):
    """Emits periodic schedule events to a channel.

    Configuration (via ``config`` dict):
        channel: Channel to publish to (default: "schedule").
        interval: Seconds between emissions (default: 1800 = 30 min).
        payload_extras: Additional fields to include in every payload.
    """

    def __init__(self, config: dict[str, Any], queue: QueueAdapter) -> None:
        self.queue = queue
        self.channel = config.get("channel", "schedule")
        self.interval = config.get("interval", 1800)
        self.payload_extras = config.get("payload_extras", {})
        self._last_emit: float = 0

    def poll(self) -> int:
        """Emit a schedule event if the interval has elapsed."""
        now = time.time()
        if now - self._last_emit < self.interval:
            return 0

        self._last_emit = now

        payload: dict[str, Any] = {
            "trigger": "schedule",
            "today": date.today().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        payload.update(self.payload_extras)

        message = Message.create(
            channel=self.channel,
            payload=payload,
            source="schedule",
        )
        self.queue.publish(message)
        log.info("Schedule event emitted to '%s'", self.channel)
        return 1
