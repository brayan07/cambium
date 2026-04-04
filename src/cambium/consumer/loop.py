"""Consumer loop — dequeues events, matches routines, executes sessions."""

from __future__ import annotations

import time

from cambium.models.routine import RoutineRegistry
from cambium.queue.base import QueueAdapter
from cambium.runner.skill_runner import SessionResult, SkillRunner


class ConsumerLoop:
    """Main event loop: dequeue, match, execute, re-enqueue."""

    def __init__(
        self,
        queue: QueueAdapter,
        routine_registry: RoutineRegistry,
        skill_runner: SkillRunner,
        poll_interval: float = 2.0,
        live: bool = False,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.skill_runner = skill_runner
        self.poll_interval = poll_interval
        self.live = live

    def tick(self) -> list[SessionResult]:
        """One iteration: dequeue events, match to routines, execute, re-enqueue emitted events."""
        all_types = self.routine_registry.subscribed_event_types()
        if not all_types:
            return []

        events = self.queue.dequeue(all_types, limit=10)
        results: list[SessionResult] = []

        for event in events:
            routines = self.routine_registry.for_event_type(event.type)

            if not routines:
                # No matching routine — ack to avoid infinite loop
                self.queue.ack(event.id)
                continue

            event_success = True
            for routine in routines:
                try:
                    config = self.skill_runner.build_session(routine, event)
                    result = self.skill_runner.execute(config, live=self.live)
                    results.append(result)

                    if result.success:
                        # Re-enqueue emitted events
                        for emitted in result.events_emitted:
                            self.queue.enqueue(emitted)
                    else:
                        event_success = False
                except Exception as exc:
                    results.append(
                        SessionResult(
                            success=False,
                            output="",
                            error=str(exc),
                        )
                    )
                    event_success = False

            if event_success:
                self.queue.ack(event.id)
            else:
                self.queue.nack(event.id)

        return results

    def run(self, max_ticks: int | None = None) -> None:
        """Main loop. Polls queue and processes events. Stops after max_ticks if set."""
        tick_count = 0
        while True:
            self.tick()
            tick_count += 1
            if max_ticks is not None and tick_count >= max_ticks:
                break
            time.sleep(self.poll_interval)
