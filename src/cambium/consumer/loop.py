"""Consumer loop — consumes messages from channels and dispatches to routines."""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future

from cambium.adapters.base import RunResult
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.base import QueueAdapter
from cambium.runner.routine_runner import RoutineRunner
from cambium.session.broadcaster import BroadcasterRegistry

log = logging.getLogger(__name__)

# Default max concurrent sessions — prevents runaway resource usage
_DEFAULT_MAX_WORKERS = 8


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
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.routine_runner = routine_runner
        self.broadcaster_registry = broadcaster_registry
        self.poll_interval = poll_interval
        self.live = live
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def _run_session(
        self,
        routine,
        message: Message,
        session_id: str,
        broadcaster=None,
    ) -> RunResult:
        """Execute a single routine session. Runs in a worker thread."""
        try:
            result = self.routine_runner.send_message(
                routine, message,
                session_id=session_id,
                live=self.live,
                on_event=broadcaster.publish if broadcaster else None,
            )

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

            return result
        except Exception as exc:
            log.exception(f"Error running routine '{routine.name}'")
            return RunResult(success=False, output="", error=str(exc))
        finally:
            if broadcaster:
                broadcaster.close()
                self.broadcaster_registry.remove(session_id)

    def tick(self) -> list[RunResult]:
        """One iteration: consume messages, dispatch to routines concurrently."""
        channels = self.routine_registry.subscribed_channels()
        if not channels:
            return []

        messages = self.queue.consume(channels, limit=10)
        if not messages:
            return []

        # Build dispatch table: group futures by message so we can ack/nack
        # each message independently once all its routines complete.
        message_futures: list[tuple[Message, list[Future]]] = []

        for message in messages:
            routines = self.routine_registry.for_channel(message.channel)

            if not routines:
                self.queue.ack(message.id)
                continue

            futures = []
            for routine in routines:
                session_id = str(uuid.uuid4())
                broadcaster = None
                if self.broadcaster_registry:
                    broadcaster = self.broadcaster_registry.create(session_id)

                future = self._executor.submit(
                    self._run_session, routine, message, session_id, broadcaster,
                )
                futures.append(future)

            message_futures.append((message, futures))

        # Wait for all dispatched sessions to complete and collect results.
        results: list[RunResult] = []
        for message, futures in message_futures:
            message_success = True
            for future in futures:
                result = future.result()  # blocks until this session finishes
                results.append(result)
                if not result.success:
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
