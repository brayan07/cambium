"""End-to-end integration test for the Cambium pipeline."""

from pathlib import Path

from cambium.adapters.base import AdapterInstanceRegistry, AdapterType, RunResult
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner
from cambium.session.broadcaster import BroadcasterRegistry


class FakeAdapter(AdapterType):
    name = "fake"

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, cwd=None):
        return RunResult(
            success=True,
            output=f"[fake] {instance.name} handled message",
            session_id=session_id,
        )


class CascadingAdapter(AdapterType):
    """Adapter that publishes to downstream channels, simulating a real LLM
    that calls POST /channels/{name}/publish during execution."""

    name = "fake"

    def __init__(self, queue: SQLiteQueue, routine_registry: RoutineRegistry):
        self._queue = queue
        self._routine_registry = routine_registry

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, cwd=None):
        # Find which routine this instance belongs to, publish to its channels
        for routine in self._routine_registry.all():
            if routine.adapter_instance == instance.name:
                for channel in routine.publish:
                    self._queue.publish(Message.create(
                        channel=channel,
                        payload={"from": routine.name, "upstream": user_message[:80]},
                        source=routine.name,
                    ))
                break

        if on_event:
            on_event({"type": "chunk", "text": f"{instance.name} output"})

        return RunResult(
            success=True,
            output=f"[cascade] {instance.name} handled message",
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


class TestCascade:
    """Test multi-hop message flow: goals → triage → tasks → executor → completions → reviewer."""

    def _setup_cascade(self, tmp_path: Path):
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        for name in ("triage", "executor", "reviewer"):
            (inst_dir / f"{name}.yaml").write_text(
                f"name: {name}\nadapter_type: fake\n"
            )

        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        (routines_dir / "triage.yaml").write_text(
            "name: triage\nadapter_instance: triage\n"
            "listen: [goals]\npublish: [tasks]\n"
        )
        (routines_dir / "executor.yaml").write_text(
            "name: executor\nadapter_instance: executor\n"
            "listen: [tasks]\npublish: [completions]\n"
        )
        (routines_dir / "reviewer.yaml").write_text(
            "name: reviewer\nadapter_instance: reviewer\n"
            "listen: [completions]\npublish: []\n"
        )

        queue = SQLiteQueue()
        routine_reg = RoutineRegistry(routines_dir)
        instance_reg = AdapterInstanceRegistry(inst_dir)
        adapter = CascadingAdapter(queue, routine_reg)
        broadcaster_reg = BroadcasterRegistry()
        runner = RoutineRunner(
            adapter_types={"fake": adapter},
            instance_registry=instance_reg,
        )
        loop = ConsumerLoop(queue, routine_reg, runner, broadcaster_registry=broadcaster_reg)
        return loop, queue, broadcaster_reg

    def test_three_hop_cascade(self, tmp_path: Path):
        """A message flows through three routines across three ticks."""
        loop, queue, _ = self._setup_cascade(tmp_path)

        # Seed the cascade
        queue.publish(Message.create(
            channel="goals", payload={"goal": "build something"}, source="user",
        ))

        # Tick 1: triage picks up goals, publishes to tasks
        results = loop.tick()
        assert len(results) == 1
        assert "triage" in results[0].output
        assert queue.pending_count(["tasks"]) == 1

        # Tick 2: executor picks up tasks, publishes to completions
        results = loop.tick()
        assert len(results) == 1
        assert "executor" in results[0].output
        assert queue.pending_count(["completions"]) == 1

        # Tick 3: reviewer picks up completions, publishes nothing
        results = loop.tick()
        assert len(results) == 1
        assert "reviewer" in results[0].output

        # Queue fully drained
        assert queue.pending_count() == 0

    def test_cascade_with_broadcaster_cleanup(self, tmp_path: Path):
        """Each hop creates and cleans up its broadcaster."""
        loop, queue, broadcaster_reg = self._setup_cascade(tmp_path)

        queue.publish(Message.create(
            channel="goals", payload={"goal": "test"}, source="user",
        ))

        for _ in range(3):
            loop.tick()

        # All broadcasters cleaned up
        assert broadcaster_reg.active_count() == 0
        assert queue.pending_count() == 0

    def test_cascade_payload_propagation(self, tmp_path: Path):
        """Downstream routines receive context from upstream via payload."""
        loop, queue, _ = self._setup_cascade(tmp_path)

        queue.publish(Message.create(
            channel="goals", payload={"goal": "test cascade"}, source="user",
        ))

        # Tick 1: triage runs
        loop.tick()

        # The message on 'tasks' should carry context from triage
        tasks_messages = queue.consume(["tasks"], limit=1)
        assert len(tasks_messages) == 1
        assert tasks_messages[0].payload["from"] == "triage"
        assert "goal" in tasks_messages[0].payload.get("upstream", "")
