"""End-to-end integration test for the Cambium pipeline."""

from pathlib import Path

from cambium.consumer.loop import ConsumerLoop
from cambium.models.event import Event
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.skill_runner import SkillRunner


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path: Path):
        """Smoke test: event -> queue -> consumer -> routine match -> session build -> ack."""
        # 1. Create skill file
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "task-mgmt.md").write_text(
            "---\n"
            "name: task-mgmt\n"
            "description: Manage tasks in the project manager\n"
            "tools:\n"
            "  - clickup\n"
            "---\n"
            "# Task Management\n\n"
            "You can create, update, and query tasks.\n"
        )

        # 2. Create prompt file
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "grooming.md").write_text(
            "You are a grooming agent. Triage and decompose tasks.\n"
        )

        # 3. Create routine YAML
        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        (routines_dir / "grooming.yaml").write_text(
            "name: grooming\n"
            "prompt_path: prompts/grooming.md\n"
            "skills:\n"
            "  - task-mgmt\n"
            "subscribe:\n"
            "  - task_queued\n"
            "emit:\n"
            "  - task_groomed\n"
        )

        # 4. Initialize all components
        skill_registry = SkillRegistry(skills_dir)
        routine_registry = RoutineRegistry(routines_dir)
        queue = SQLiteQueue()
        runner = SkillRunner(skill_registry)
        loop = ConsumerLoop(queue, routine_registry, runner)

        # 5. Enqueue a test event
        event = Event.create(
            type="task_queued",
            payload={"task_id": "abc123", "title": "Fix the widget"},
            source="test_harness",
        )
        queue.enqueue(event)
        assert queue.pending_count() == 1

        # 6. Run one tick
        results = loop.tick()

        # 7. Verify
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert "grooming" in result.output

        # Event should be acked (no longer pending)
        assert queue.pending_count() == 0

    def test_event_with_no_subscriber_is_ignored(self, tmp_path: Path):
        """Events with types no routine subscribes to just sit in the queue."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        (routines_dir / "handler.yaml").write_text(
            "prompt_path: ''\nskills: []\nsubscribe: [task_queued]\n"
        )

        queue = SQLiteQueue()
        skill_registry = SkillRegistry(skills_dir)
        routine_registry = RoutineRegistry(routines_dir)
        runner = SkillRunner(skill_registry)
        loop = ConsumerLoop(queue, routine_registry, runner)

        # Enqueue an event type nobody subscribes to
        event = Event.create(type="unknown_type", payload={}, source="test")
        queue.enqueue(event)

        results = loop.tick()
        assert results == []
        # Event is still pending — it was never dequeued because no routine subscribes
        assert queue.pending_count() == 1

    def test_multi_skill_session_prompt(self, tmp_path: Path):
        """Verify that multiple skills are concatenated into the session prompt."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "alpha.md").write_text(
            "---\nname: alpha\ntools: [tool_a]\n---\n# Alpha content\n"
        )
        (skills_dir / "beta.md").write_text(
            "---\nname: beta\ntools: [tool_b]\n---\n# Beta content\n"
        )

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "multi.md").write_text("Multi-skill prompt.\n")

        routines_dir = tmp_path / "routines"
        routines_dir.mkdir()
        (routines_dir / "multi.yaml").write_text(
            "name: multi\n"
            "prompt_path: prompts/multi.md\n"
            "skills: [alpha, beta]\n"
            "subscribe: [trigger]\n"
        )

        skill_registry = SkillRegistry(skills_dir)
        routine_registry = RoutineRegistry(routines_dir)
        runner = SkillRunner(skill_registry)

        event = Event.create(type="trigger", payload={}, source="test")
        routine = routine_registry.get("multi")
        config = runner.build_session(routine, event, prompt_base_dir=tmp_path)

        assert "Multi-skill prompt." in config.prompt
        assert "Alpha content" in config.prompt
        assert "Beta content" in config.prompt
        assert "tool_a" in config.tools
        assert "tool_b" in config.tools
