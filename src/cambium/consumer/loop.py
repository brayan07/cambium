"""Consumer loop — consumes messages from channels and dispatches to routines."""

from __future__ import annotations

import logging
import time

from cambium.adapters.base import RunResult
from cambium.models.routine import RoutineRegistry
from cambium.queue.base import QueueAdapter
from cambium.runner.routine_runner import RoutineRunner

log = logging.getLogger(__name__)


class ConsumerLoop:
    """Main loop: consume messages, match to routines, execute via adapter."""

    def __init__(
        self,
        queue: QueueAdapter,
        routine_registry: RoutineRegistry,
        routine_runner: RoutineRunner,
        poll_interval: float = 2.0,
        live: bool = False,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.routine_runner = routine_runner
        self.poll_interval = poll_interval
        self.live = live

    def tick(self) -> list[RunResult]:
        """One iteration: consume messages, match to routines, execute."""
        channels = self.routine_registry.subscribed_channels()
        if not channels:
            return []

        messages = self.queue.consume(channels, limit=10)
        results: list[RunResult] = []

        for message in messages:
            routines = self.routine_registry.for_channel(message.channel)

            if not routines:
                self.queue.ack(message.id)
                continue

            message_success = True
            for routine in routines:
                try:
                    result = self.routine_runner.send_message(
                        routine, message, live=self.live,
                    )
                    results.append(result)

                    if not result.success:
                        message_success = False
                except Exception as exc:
                    log.exception(f"Error running routine '{routine.name}'")
                    results.append(
                        RunResult(success=False, output="", error=str(exc))
                    )
                    message_success = False

            if message_success:
                self.queue.ack(message.id)
            else:
                self.queue.nack(message.id)

        return results

    def run(self, max_ticks: int | None = None) -> None:
        """Main loop. Polls queue and processes messages."""
        tick_count = 0
        while True:
            self.tick()
            tick_count += 1
            if max_ticks is not None and tick_count >= max_ticks:
                break
            time.sleep(self.poll_interval)
