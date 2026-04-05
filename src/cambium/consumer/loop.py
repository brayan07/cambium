"""Consumer loop — consumes messages from channels and dispatches to routines."""

from __future__ import annotations

import logging
import time
import uuid

from cambium.adapters.base import RunResult
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.base import QueueAdapter
from cambium.runner.routine_runner import RoutineRunner
from cambium.session.broadcaster import BroadcasterRegistry

log = logging.getLogger(__name__)


class ConsumerLoop:
    """Main loop: consume messages, match to routines, execute via adapter."""

    def __init__(
        self,
        queue: QueueAdapter,
        routine_registry: RoutineRegistry,
        routine_runner: RoutineRunner,
        broadcaster_registry: BroadcasterRegistry | None = None,
        poll_interval: float = 2.0,
        live: bool = False,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.routine_runner = routine_runner
        self.broadcaster_registry = broadcaster_registry
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
                session_id = str(uuid.uuid4())
                broadcaster = None
                if self.broadcaster_registry:
                    broadcaster = self.broadcaster_registry.create(session_id)

                try:
                    result = self.routine_runner.send_message(
                        routine, message,
                        session_id=session_id,
                        live=self.live,
                        on_event=broadcaster.publish if broadcaster else None,
                    )
                    results.append(result)

                    # Notify consolidator — but skip consolidator's own sessions
                    # to avoid infinite recursion.
                    if routine.name != "consolidator":
                        self.queue.publish(Message.create(
                            channel="sessions_completed",
                            payload={
                                "session_id": session_id,
                                "routine_name": routine.name,
                                "success": result.success,
                                "trigger_channel": message.channel,
                            },
                            source="system",
                        ))

                    if not result.success:
                        message_success = False
                except Exception as exc:
                    log.exception(f"Error running routine '{routine.name}'")
                    results.append(
                        RunResult(success=False, output="", error=str(exc))
                    )
                    message_success = False
                finally:
                    if broadcaster:
                        broadcaster.close()
                        self.broadcaster_registry.remove(session_id)

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
