"""Tests for the consumer loop."""

from __future__ import annotations

from pathlib import Path

from cambium.adapters.base import AdapterInstance, AdapterInstanceRegistry, AdapterType, RunResult
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner
from cambium.session.broadcaster import BroadcasterRegistry


class FakeAdapter(AdapterType):
    """A fake adapter that returns configurable results."""

    name = "fake"

    def __init__(self, result: RunResult | None = None):
        self._result = result or RunResult(success=True, output="[fake] done")

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, cwd=None):
        if on_event:
            on_event({"type": "chunk", "text": "hello"})
        return RunResult(
            success=self._result.success,
            output=self._result.output,
            error=self._result.error,
            session_id=session_id,
        )


def _make_routines_dir(tmp_path: Path, routines: list[tuple[str, str]]) -> Path:
    d = tmp_path / "routines"
    d.mkdir(exist_ok=True)
    for name, content in routines:
        (d / name).write_text(content)
    return d


def _make_instances_dir(tmp_path: Path) -> Path:
    d = tmp_path / "instances"
    d.mkdir(exist_ok=True)
    (d / "basic.yaml").write_text("name: basic\nadapter_type: fake\n")
    return d


def _make_loop(tmp_path, routines, adapter=None) -> tuple[ConsumerLoop, SQLiteQueue]:
    routine_dir = _make_routines_dir(tmp_path, routines)
    instance_dir = _make_instances_dir(tmp_path)

    queue = SQLiteQueue()
    routine_reg = RoutineRegistry(routine_dir)
    instance_reg = AdapterInstanceRegistry(instance_dir)
    adapter = adapter or FakeAdapter()
    runner = RoutineRunner(
        adapter_types={adapter.name: adapter},
        instance_registry=instance_reg,
    )
    loop = ConsumerLoop(queue, routine_reg, runner)
    return loop, queue


class TestConsumerLoop:
    def test_message_matches_correct_routine(self, tmp_path: Path):
        loop, queue = _make_loop(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: basic\nlisten: [tasks]\n"),
            ("other.yaml", "name: other\nadapter_instance: basic\nlisten: [reviews]\n"),
        ])
        queue.publish(Message.create(channel="tasks", payload={}, source="test"))

        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is True

    def test_failed_execution_nacks_message(self, tmp_path: Path):
        adapter = FakeAdapter(RunResult(success=False, output="", error="boom"))
        loop, queue = _make_loop(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: basic\nlisten: [tasks]\n"),
        ], adapter=adapter)
        queue.publish(Message.create(channel="tasks", payload={}, source="test"))

        loop.tick()
        assert queue.pending_count(["tasks"]) == 1

    def test_no_matching_routine_acks_message(self, tmp_path: Path):
        loop, queue = _make_loop(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: basic\nlisten: [tasks, other]\n"),
        ])
        queue.publish(Message.create(channel="other", payload={}, source="test"))

        results = loop.tick()
        assert len(results) == 1
        assert queue.pending_count() == 0

    def test_max_ticks_stops_loop(self, tmp_path: Path):
        loop, _ = _make_loop(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: basic\nlisten: [x]\n"),
        ])
        loop.poll_interval = 0.0
        loop.run(max_ticks=3)

    def test_missing_adapter_instance_returns_error(self, tmp_path: Path):
        routine_dir = _make_routines_dir(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: nonexistent\nlisten: [tasks]\n"),
        ])
        instance_dir = _make_instances_dir(tmp_path)

        queue = SQLiteQueue()
        routine_reg = RoutineRegistry(routine_dir)
        instance_reg = AdapterInstanceRegistry(instance_dir)
        runner = RoutineRunner(
            adapter_types={"fake": FakeAdapter()},
            instance_registry=instance_reg,
        )
        loop = ConsumerLoop(queue, routine_reg, runner)
        queue.publish(Message.create(channel="tasks", payload={}, source="test"))

        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is False
        assert "not found" in results[0].error

    def test_broadcaster_receives_chunks(self, tmp_path: Path):
        """One-shot executions stream chunks through a broadcaster."""
        broadcaster_reg = BroadcasterRegistry()
        loop, queue = _make_loop(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: basic\nlisten: [tasks]\n"),
        ])
        loop.broadcaster_registry = broadcaster_reg

        queue.publish(Message.create(channel="tasks", payload={}, source="test"))
        results = loop.tick()

        assert len(results) == 1
        assert results[0].success is True
        # Broadcaster should have been created and cleaned up
        assert broadcaster_reg.active_count() == 0

    def test_broadcaster_closed_on_failure(self, tmp_path: Path):
        """Broadcaster is cleaned up even when execution fails."""
        broadcaster_reg = BroadcasterRegistry()
        adapter = FakeAdapter(RunResult(success=False, output="", error="boom"))
        loop, queue = _make_loop(tmp_path, [
            ("handler.yaml", "name: handler\nadapter_instance: basic\nlisten: [tasks]\n"),
        ], adapter=adapter)
        loop.broadcaster_registry = broadcaster_reg

        queue.publish(Message.create(channel="tasks", payload={}, source="test"))
        loop.tick()

        assert broadcaster_reg.active_count() == 0
