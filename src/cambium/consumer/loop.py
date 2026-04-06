"""Consumer loop — consumes messages from channels and dispatches to routines."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future

from cambium.adapters.base import RunResult
from cambium.models.message import Message
from cambium.models.routine import Routine, RoutineRegistry
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

        # Per-routine concurrency tracking
        self._running: dict[str, int] = {}  # routine_name -> active session count
        self._running_lock = threading.Lock()

        # Batch buffering: routine_name -> list of (message, routine) tuples
        self._batch_buffers: dict[str, list[tuple[Message, Routine]]] = {}
        self._batch_deadlines: dict[str, float] = {}  # routine_name -> deadline timestamp

    # --- Concurrency tracking ---

    def _has_capacity(self, routine: Routine) -> bool:
        if routine.max_concurrency <= 0:
            return True
        with self._running_lock:
            return self._running.get(routine.name, 0) < routine.max_concurrency

    def _increment_running(self, routine_name: str) -> None:
        with self._running_lock:
            self._running[routine_name] = self._running.get(routine_name, 0) + 1

    def _decrement_running(self, routine_name: str) -> None:
        with self._running_lock:
            count = self._running.get(routine_name, 0)
            self._running[routine_name] = max(0, count - 1)

    # --- Batch management ---

    def _is_batched(self, routine: Routine) -> bool:
        return routine.batch_window > 0 and routine.batch_max > 1

    def _buffer_message(self, routine: Routine, message: Message) -> None:
        """Add a message to the routine's batch buffer."""
        name = routine.name
        if name not in self._batch_buffers:
            self._batch_buffers[name] = []
            self._batch_deadlines[name] = time.monotonic() + routine.batch_window

        self._batch_buffers[name].append((message, routine))

        # Flush if at capacity
        if len(self._batch_buffers[name]) >= routine.batch_max:
            self._flush_batch(name)

    def _flush_expired_batches(self) -> list[Future]:
        """Dispatch any batch buffers whose window has expired."""
        futures = []
        now = time.monotonic()
        expired = [
            name for name, deadline in self._batch_deadlines.items()
            if now >= deadline and name in self._batch_buffers
        ]
        for name in expired:
            futures.extend(self._flush_batch(name))
        return futures

    def _flush_batch(self, routine_name: str) -> list[Future]:
        """Dispatch a batch and return the futures."""
        buffer = self._batch_buffers.pop(routine_name, [])
        self._batch_deadlines.pop(routine_name, None)

        if not buffer:
            return []

        messages = [msg for msg, _ in buffer]
        routine = buffer[0][1]  # all entries share the same routine

        if not self._has_capacity(routine):
            # Can't dispatch yet — requeue all messages
            for msg in messages:
                self.queue.requeue(msg.id)
            return []

        # Build combined payload
        combined_payload = {
            "batch": True,
            "count": len(messages),
            "messages": [
                {
                    "id": msg.id,
                    "channel": msg.channel,
                    "payload": msg.payload,
                    "source": msg.source,
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in messages
            ],
        }

        session_id = str(uuid.uuid4())
        broadcaster = None
        if self.broadcaster_registry:
            broadcaster = self.broadcaster_registry.create(session_id)

        # Create a synthetic message for the batch
        batch_message = Message.create(
            channel=messages[0].channel,
            payload=combined_payload,
            source="batch",
        )

        self._increment_running(routine.name)
        future = self._executor.submit(
            self._run_session, routine, batch_message, session_id, broadcaster,
        )
        future.add_done_callback(lambda _: self._decrement_running(routine.name))

        # Ack/nack original messages based on batch result
        def _handle_batch_result(f: Future) -> None:
            result = f.result()
            for msg in messages:
                if result.success:
                    self.queue.ack(msg.id)
                else:
                    self.queue.nack(msg.id)

        future.add_done_callback(_handle_batch_result)
        return [future]

    # --- Session execution ---

    def _run_session(
        self,
        routine: Routine,
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

            # Notify downstream routines (e.g., session-summarizer) unless
            # the routine has suppress_completion_event set.
            if not routine.suppress_completion_event:
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

    # --- Main loop ---

    def tick(self) -> list[RunResult]:
        """One iteration: consume messages, dispatch to routines concurrently."""
        # 1. Flush any expired batch buffers
        batch_futures = self._flush_expired_batches()

        # 2. Consume messages
        channels = self.routine_registry.subscribed_channels()
        if not channels:
            return []

        messages = self.queue.consume(channels, limit=10)

        # 3. Dispatch or buffer each message
        message_futures: list[tuple[Message, list[Future]]] = []

        for message in messages:
            routines = self.routine_registry.for_channel(message.channel)

            # Target filtering — heartbeat timers specify which routine to wake
            target = message.payload.get("target") if message.payload else None
            if target:
                routines = [r for r in routines if r.name == target]

            if not routines:
                self.queue.ack(message.id)
                continue

            # Check: can any routine handle this message right now?
            dispatchable = [r for r in routines if self._has_capacity(r)]
            batchable = [r for r in routines if self._is_batched(r)]

            # All batchable routines get buffered (regardless of capacity — batch
            # will check capacity when it flushes)
            for routine in batchable:
                self._buffer_message(routine, message)

            # Non-batched routines dispatch immediately if they have capacity
            non_batched = [r for r in routines if not self._is_batched(r)]
            non_batched_ready = [r for r in non_batched if r in dispatchable]

            if not non_batched_ready and not batchable:
                # Nothing can handle this message right now — requeue
                self.queue.requeue(message.id)
                continue

            if batchable and not non_batched_ready:
                # Only batched routines matched — message was buffered, skip dispatch
                continue

            futures = []
            for routine in non_batched_ready:
                session_id = str(uuid.uuid4())
                broadcaster = None
                if self.broadcaster_registry:
                    broadcaster = self.broadcaster_registry.create(session_id)

                self._increment_running(routine.name)
                future = self._executor.submit(
                    self._run_session, routine, message, session_id, broadcaster,
                )
                future.add_done_callback(
                    lambda _, rn=routine.name: self._decrement_running(rn)
                )
                futures.append(future)

            message_futures.append((message, futures))

        # 4. Wait for all non-batch dispatched sessions to complete
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

        # 5. Collect results from batch futures too
        for future in batch_futures:
            try:
                result = future.result()
                results.append(result)
            except Exception:
                pass

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
