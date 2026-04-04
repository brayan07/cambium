"""End-to-end integration test for the Cambium pipeline."""

from pathlib import Path

from cambium.adapters.base import AdapterInstanceRegistry, AdapterType, RunResult
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner


class FakeAdapter(AdapterType):
    name = "fake"

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None):
        return RunResult(
            success=True,
            output=f"[fake] {instance.name} handled message",
            session_id=session_id,
        )


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path: Path):
        """Smoke test: message -> queue -> consumer -> routine match -> execute -> ack."""
        # Adapter instance
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        (inst_dir / "triage.yaml").write_text(
            "name: triage\nadapter_type: fake\n"
            "config:\n  model: haiku\n"
        )

        # Routine
        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        (routines_dir / "triage.yaml").write_text(
            "name: triage\n"
            "adapter_instance: triage\n"
            "listen: [goals]\n"
            "publish: [tasks]\n"
        )

        # Wire up
        queue = SQLiteQueue()
        routine_reg = RoutineRegistry(routines_dir)
        instance_reg = AdapterInstanceRegistry(inst_dir)
        adapter = FakeAdapter()
        runner = RoutineRunner(
            adapter_types={"fake": adapter},
            instance_registry=instance_reg,
        )
        loop = ConsumerLoop(queue, routine_reg, runner)

        # Publish a message
        msg = Message.create(channel="goals", payload={"goal": "test"}, source="test")
        queue.publish(msg)
        assert queue.pending_count() == 1

        # Run one tick
        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is True
        assert "triage" in results[0].output
        assert queue.pending_count() == 0

    def test_message_with_no_listener_stays_pending(self, tmp_path: Path):
        """Messages on channels nobody listens to stay in the queue."""
        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()

        (inst_dir / "basic.yaml").write_text("name: basic\nadapter_type: fake\n")
        (routines_dir / "handler.yaml").write_text(
            "name: handler\nadapter_instance: basic\nlisten: [tasks]\n"
        )

        queue = SQLiteQueue()
        routine_reg = RoutineRegistry(routines_dir)
        instance_reg = AdapterInstanceRegistry(inst_dir)
        runner = RoutineRunner(
            adapter_types={"fake": FakeAdapter()},
            instance_registry=instance_reg,
        )
        loop = ConsumerLoop(queue, routine_reg, runner)

        # Publish to a channel nobody listens on
        queue.publish(Message.create(channel="unknown", payload={}, source="test"))

        results = loop.tick()
        assert results == []
        # Message stays pending — never consumed because no routine listens
        assert queue.pending_count() == 1

    def test_fan_out_to_multiple_routines(self, tmp_path: Path):
        """Multiple routines listening on the same channel all execute."""
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        (inst_dir / "basic.yaml").write_text("name: basic\nadapter_type: fake\n")

        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        (routines_dir / "a.yaml").write_text(
            "name: a\nadapter_instance: basic\nlisten: [events]\n"
        )
        (routines_dir / "b.yaml").write_text(
            "name: b\nadapter_instance: basic\nlisten: [events]\n"
        )

        queue = SQLiteQueue()
        routine_reg = RoutineRegistry(routines_dir)
        instance_reg = AdapterInstanceRegistry(inst_dir)
        runner = RoutineRunner(
            adapter_types={"fake": FakeAdapter()},
            instance_registry=instance_reg,
        )
        loop = ConsumerLoop(queue, routine_reg, runner)

        queue.publish(Message.create(channel="events", payload={}, source="test"))
        results = loop.tick()
        assert len(results) == 2
        assert all(r.success for r in results)
        assert queue.pending_count() == 0
