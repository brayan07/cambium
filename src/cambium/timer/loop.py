"""Timer loop — publishes messages on cron schedules."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from croniter import croniter

from cambium.models.message import Message
from cambium.queue.base import QueueAdapter
from cambium.timer.model import TimerConfig

log = logging.getLogger(__name__)


class TimerLoop:
    """Check timers against cron schedules and publish messages when due."""

    def __init__(
        self,
        timers: list[TimerConfig],
        queue: QueueAdapter,
    ) -> None:
        self.timers = timers
        self.queue = queue
        self._last_fired: dict[str, datetime] = {}

    def tick(self, now: datetime | None = None) -> int:
        """Check which timers are due and publish messages. Returns count fired."""
        now = now or datetime.now(timezone.utc)
        fired = 0

        for timer in self.timers:
            if self._is_due(timer, now):
                self.queue.publish(Message.create(
                    channel=timer.channel,
                    payload=timer.payload,
                    source=f"timer:{timer.name}",
                ))
                self._last_fired[timer.name] = now
                fired += 1
                log.debug(f"Timer '{timer.name}' fired → {timer.channel}")

        return fired

    def _is_due(self, timer: TimerConfig, now: datetime) -> bool:
        """Check if a timer should fire based on its cron schedule.

        A timer fires if the current minute matches its cron expression
        AND it hasn't already fired in the current minute.
        """
        # Truncate to minute resolution for cron matching
        now_minute = now.replace(second=0, microsecond=0)

        # Don't fire twice in the same minute
        last = self._last_fired.get(timer.name)
        if last is not None:
            last_minute = last.replace(second=0, microsecond=0)
            if last_minute >= now_minute:
                return False

        # Check if the current minute matches the cron expression.
        # croniter.match returns True if the given datetime matches the cron.
        return croniter.match(timer.schedule, now_minute)
