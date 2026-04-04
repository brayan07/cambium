#!/usr/bin/env python3
"""Demo: end-to-end Cambium event flow with real claude -p execution.

Usage:
    uv run python demo.py                    # mock execution (fast, no LLM)
    uv run python demo.py --live             # real claude -p execution
    uv run python demo.py --live --timeout 60
"""

import argparse
import logging
import tempfile
from pathlib import Path

from cambium.consumer.loop import ConsumerLoop
from cambium.models.event import Event
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.skill_runner import SkillRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("demo")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambium end-to-end demo")
    parser.add_argument("--live", action="store_true", help="Use real claude -p execution")
    parser.add_argument("--timeout", type=int, default=120, help="Execution timeout in seconds")
    args = parser.parse_args()

    framework_dir = Path(__file__).parent
    user_dir = Path.home() / ".cambium"

    # Set up components
    log.info("Setting up Cambium components...")

    # Queue — use temp file for demo
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    queue = SQLiteQueue(db_path)

    # Skill registry — framework defaults + user overrides
    skill_dirs = [framework_dir / "defaults" / "skills"]
    if (user_dir / "skills").exists():
        skill_dirs.append(user_dir / "skills")
    skill_registry = SkillRegistry(*skill_dirs)
    log.info(f"Loaded {len(skill_registry.all())} skills: {skill_registry.names()}")

    # Routine registry
    routine_dirs = [framework_dir / "defaults" / "routines"]
    if (user_dir / "routines").exists():
        routine_dirs.append(user_dir / "routines")
    routine_registry = RoutineRegistry(*routine_dirs)
    log.info(f"Loaded {len(routine_registry.all())} routines: {[r.name for r in routine_registry.all()]}")
    log.info(f"Subscribed event types: {routine_registry.subscribed_event_types()}")

    # Skill runner
    skill_runner = SkillRunner(skill_registry)

    # Consumer loop
    consumer = ConsumerLoop(
        queue=queue,
        routine_registry=routine_registry,
        skill_runner=skill_runner,
        live=args.live,
    )

    # Enqueue a test event
    test_event = Event.create(
        type="goal_created",
        payload={
            "goal": "Research the best Python testing frameworks and recommend one for a new project",
            "context": "Small CLI tool, needs fast tests, good assertion messages",
        },
        source="demo",
    )
    queue.enqueue(test_event)
    log.info(f"Enqueued event: {test_event.type} (id={test_event.id[:8]}...)")
    log.info(f"Queue has {queue.pending_count()} pending events")

    # Run one tick
    mode = "LIVE (claude -p)" if args.live else "MOCK"
    log.info(f"Running one consumer tick [{mode}]...")
    results = consumer.tick()

    # Report
    log.info(f"Tick completed: {len(results)} session(s) executed")
    for i, result in enumerate(results):
        status = "✓" if result.success else "✗"
        log.info(f"  Session {i+1}: {status} ({result.duration_seconds:.1f}s)")
        if result.output:
            # Truncate for display
            preview = result.output[:500]
            if len(result.output) > 500:
                preview += f"... ({len(result.output)} chars total)"
            log.info(f"  Output: {preview}")
        if result.error:
            log.info(f"  Error: {result.error}")

    log.info(f"Queue status: {queue.pending_count()} pending events remaining")

    # Clean up
    Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
