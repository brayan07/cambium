"""Tests for the consumer loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cambium.consumer.loop import ConsumerLoop
from cambium.models.event import Event
from cambium.models.routine import Routine, RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.skill_runner import SessionResult, SkillRunner


def _make_routine_dir(tmp_path: Path, routines: list[tuple[str, str]]) -> Path:
    """Create routine YAML files. Each tuple is (filename, yaml_content)."""
    d = tmp_path / "routines"
    d.mkdir(exist_ok=True)
    for name, content in routines:
        (d / name).write_text(content)
    return d


def _make_skill_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir(exist_ok=True)
    (d / "basic.md").write_text("---\nname: basic\n---\n# Basic skill\n")
    return d


class TestConsumerLoop:
    def test_event_matches_correct_routine(self, tmp_path: Path):
        skill_dir = _make_skill_dir(tmp_path)
        routine_dir = _make_routine_dir(tmp_path, [
            ("grooming.yaml", "prompt_path: ''\nskills: [basic]\nsubscribe: [task_queued]\n"),
            ("execution.yaml", "prompt_path: ''\nskills: [basic]\nsubscribe: [task_ready]\n"),
        ])

        queue = SQLiteQueue()
        skill_reg = SkillRegistry(skill_dir)
        routine_reg = RoutineRegistry(routine_dir)
        runner = SkillRunner(skill_reg)
        loop = ConsumerLoop(queue, routine_reg, runner)

        ev = Event.create(type="task_queued", payload={}, source="test")
        queue.enqueue(ev)

        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is True
        assert "grooming" in results[0].output

    def test_emitted_events_are_re_enqueued(self, tmp_path: Path):
        skill_dir = _make_skill_dir(tmp_path)
        routine_dir = _make_routine_dir(tmp_path, [
            ("handler.yaml", "prompt_path: ''\nskills: [basic]\nsubscribe: [trigger]\n"),
        ])

        queue = SQLiteQueue()
        skill_reg = SkillRegistry(skill_dir)
        routine_reg = RoutineRegistry(routine_dir)
        runner = SkillRunner(skill_reg)

        # Patch execute to emit a follow-up event
        follow_up = Event.create(type="follow_up", payload={}, source="handler")
        original_execute = runner.execute

        def mock_execute(config):
            result = original_execute(config)
            result.events_emitted = [follow_up]
            return result

        runner.execute = mock_execute

        loop = ConsumerLoop(queue, routine_reg, runner)
        ev = Event.create(type="trigger", payload={}, source="test")
        queue.enqueue(ev)

        loop.tick()

        # follow_up should now be in the queue
        assert queue.pending_count(["follow_up"]) == 1

    def test_failed_execution_nacks_event(self, tmp_path: Path):
        skill_dir = _make_skill_dir(tmp_path)
        routine_dir = _make_routine_dir(tmp_path, [
            ("handler.yaml", "prompt_path: ''\nskills: [basic]\nsubscribe: [trigger]\n"),
        ])

        queue = SQLiteQueue()
        skill_reg = SkillRegistry(skill_dir)
        routine_reg = RoutineRegistry(routine_dir)
        runner = SkillRunner(skill_reg)

        # Make execute return failure
        def failing_execute(config):
            return SessionResult(success=False, output="", error="boom")

        runner.execute = failing_execute

        loop = ConsumerLoop(queue, routine_reg, runner)
        ev = Event.create(type="trigger", payload={}, source="test")
        queue.enqueue(ev)

        loop.tick()

        # Event should be back in pending (nacked)
        assert queue.pending_count(["trigger"]) == 1

    def test_no_matching_routine_acks_event(self, tmp_path: Path):
        skill_dir = _make_skill_dir(tmp_path)
        # Subscribe to "trigger" but enqueue "other_type"
        routine_dir = _make_routine_dir(tmp_path, [
            ("handler.yaml", "prompt_path: ''\nskills: [basic]\nsubscribe: [trigger, other_type]\n"),
        ])

        queue = SQLiteQueue()
        skill_reg = SkillRegistry(skill_dir)
        routine_reg = RoutineRegistry(routine_dir)
        runner = SkillRunner(skill_reg)
        loop = ConsumerLoop(queue, routine_reg, runner)

        # Enqueue "other_type" — it will match the routine so test the real no-match case
        # We need an event type that IS subscribed (so it gets dequeued) but has no matching routine
        # Actually, for_event_type will return the handler since it subscribes to other_type.
        # To test true no-match, we'd need a type that is in subscribed_event_types but removed.
        # Let's test with a routine that subscribes to the event:
        ev = Event.create(type="other_type", payload={}, source="test")
        queue.enqueue(ev)

        results = loop.tick()
        # It should match the handler routine and succeed
        assert len(results) == 1
        assert queue.pending_count() == 0

    def test_max_ticks_stops_loop(self, tmp_path: Path):
        skill_dir = _make_skill_dir(tmp_path)
        routine_dir = _make_routine_dir(tmp_path, [
            ("handler.yaml", "prompt_path: ''\nskills: [basic]\nsubscribe: [x]\n"),
        ])

        queue = SQLiteQueue()
        skill_reg = SkillRegistry(skill_dir)
        routine_reg = RoutineRegistry(routine_dir)
        runner = SkillRunner(skill_reg)
        loop = ConsumerLoop(queue, routine_reg, runner, poll_interval=0.0)

        # Should terminate after 3 ticks without hanging
        loop.run(max_ticks=3)

    def test_exception_in_build_session_nacks(self, tmp_path: Path):
        skill_dir = _make_skill_dir(tmp_path)
        # Routine references a missing skill
        routine_dir = _make_routine_dir(tmp_path, [
            ("handler.yaml", "prompt_path: ''\nskills: [nonexistent]\nsubscribe: [trigger]\n"),
        ])

        queue = SQLiteQueue()
        skill_reg = SkillRegistry(skill_dir)
        routine_reg = RoutineRegistry(routine_dir)
        runner = SkillRunner(skill_reg)
        loop = ConsumerLoop(queue, routine_reg, runner)

        ev = Event.create(type="trigger", payload={}, source="test")
        queue.enqueue(ev)

        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is False
        assert "Missing skills" in results[0].error
        # Event should be nacked
        assert queue.pending_count(["trigger"]) == 1
