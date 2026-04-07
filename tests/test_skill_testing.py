"""Integration test for the skill-testing routine.

Verifies the end-to-end flow: skill event → skill-testing routine → pass/fail result.
"""

from pathlib import Path

from cambium.adapters.base import AdapterInstanceRegistry, AdapterType, RunResult
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner


class SkillTestAdapter(AdapterType):
    """Adapter that simulates the skill-testing routine publishing a pass/fail result."""

    name = "fake"

    def __init__(self, queue: SQLiteQueue, routine_registry: RoutineRegistry, pass_test: bool = True):
        self._queue = queue
        self._routine_registry = routine_registry
        self._pass_test = pass_test

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, on_raw_event=None,
                     cwd=None, resume=False):
        for routine in self._routine_registry.all():
            if routine.adapter_instance == instance.name:
                # Simulate publishing test result
                if self._pass_test:
                    channel = "skill_test_passed"
                    payload = {
                        "skill_name": "echo",
                        "skill_dir": "defaults/adapters/claude-code/skills/echo",
                        "trigger_channel": "skill_updated",
                        "preset": "smoke",
                        "pass_rate": 1.0,
                        "summary": "All 5 trials passed",
                    }
                else:
                    channel = "skill_test_failed"
                    payload = {
                        "skill_name": "echo",
                        "skill_dir": "defaults/adapters/claude-code/skills/echo",
                        "trigger_channel": "skill_updated",
                        "preset": "smoke",
                        "pass_rate": 0.4,
                        "failures": ["echo-basic: expected output not found"],
                        "summary": "2 of 5 trials passed (0.4 < 0.8 threshold)",
                    }

                if channel in routine.publish:
                    self._queue.publish(Message.create(
                        channel=channel,
                        payload=payload,
                        source=routine.name,
                    ))
                break

        return RunResult(
            success=True,
            output=f"[skill-test] {instance.name} evaluated skill",
            session_id=session_id,
        )


def _setup(tmp_path: Path, pass_test: bool = True):
    """Set up a minimal skill-testing pipeline."""
    inst_dir = tmp_path / "instances"
    inst_dir.mkdir()
    (inst_dir / "skill-testing.yaml").write_text(
        "name: skill-testing\nadapter_type: fake\nconfig:\n  model: sonnet\n"
    )

    routines_dir = tmp_path / "routines"
    routines_dir.mkdir()
    (routines_dir / "skill-testing.yaml").write_text(
        "name: skill-testing\n"
        "adapter_instance: skill-testing\n"
        "listen: [skill_created, skill_updated, skill_deploy_requested]\n"
        "publish: [skill_test_passed, skill_test_failed]\n"
        "max_concurrency: 1\n"
    )

    queue = SQLiteQueue()
    routine_reg = RoutineRegistry(routines_dir)
    instance_reg = AdapterInstanceRegistry(inst_dir)
    adapter = SkillTestAdapter(queue, routine_reg, pass_test=pass_test)
    runner = RoutineRunner(
        adapter_types={"fake": adapter},
        instance_registry=instance_reg,
    )
    loop = ConsumerLoop(queue, routine_reg, runner)
    return loop, queue


class TestSkillTestingRoutine:
    def test_skill_updated_triggers_testing(self, tmp_path: Path):
        """Emitting skill_updated triggers the skill-testing routine."""
        loop, queue = _setup(tmp_path)

        queue.publish(Message.create(
            channel="skill_updated",
            payload={
                "skill_name": "echo",
                "skill_dir": "defaults/adapters/claude-code/skills/echo",
                "changed_files": ["SKILL.md"],
            },
            source="test",
        ))

        assert queue.pending_count(["skill_updated"]) == 1
        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is True
        assert queue.pending_count(["skill_updated"]) == 0

    def test_skill_created_triggers_testing(self, tmp_path: Path):
        """Emitting skill_created triggers the skill-testing routine."""
        loop, queue = _setup(tmp_path)

        queue.publish(Message.create(
            channel="skill_created",
            payload={
                "skill_name": "new-skill",
                "skill_dir": "defaults/adapters/claude-code/skills/new-skill",
            },
            source="test",
        ))

        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is True

    def test_skill_deploy_requested_triggers_testing(self, tmp_path: Path):
        """Emitting skill_deploy_requested triggers the skill-testing routine."""
        loop, queue = _setup(tmp_path)

        queue.publish(Message.create(
            channel="skill_deploy_requested",
            payload={
                "skill_name": "echo",
                "skill_dir": "defaults/adapters/claude-code/skills/echo",
            },
            source="test",
        ))

        results = loop.tick()
        assert len(results) == 1
        assert results[0].success is True

    def test_pass_emits_skill_test_passed(self, tmp_path: Path):
        """On successful evaluation, skill_test_passed is published."""
        loop, queue = _setup(tmp_path, pass_test=True)

        queue.publish(Message.create(
            channel="skill_updated",
            payload={"skill_name": "echo", "skill_dir": "skills/echo"},
            source="test",
        ))

        loop.tick()

        # The adapter simulated publishing to skill_test_passed
        assert queue.pending_count(["skill_test_passed"]) == 1
        assert queue.pending_count(["skill_test_failed"]) == 0

    def test_fail_emits_skill_test_failed(self, tmp_path: Path):
        """On failed evaluation, skill_test_failed is published."""
        loop, queue = _setup(tmp_path, pass_test=False)

        queue.publish(Message.create(
            channel="skill_updated",
            payload={"skill_name": "echo", "skill_dir": "skills/echo"},
            source="test",
        ))

        loop.tick()

        assert queue.pending_count(["skill_test_failed"]) == 1
        assert queue.pending_count(["skill_test_passed"]) == 0

    def test_routine_yaml_matches_defaults(self):
        """The default routine YAML parses correctly and has expected channels."""
        routines_dir = Path(__file__).parent.parent / "defaults" / "routines"
        registry = RoutineRegistry(routines_dir)
        routine = registry.get("skill-testing")
        assert routine is not None
        assert set(routine.listen) == {"skill_created", "skill_updated", "skill_deploy_requested"}
        assert set(routine.publish) == {"skill_test_passed", "skill_test_failed"}
        assert routine.adapter_instance == "skill-testing"
