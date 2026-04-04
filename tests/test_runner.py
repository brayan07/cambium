"""Tests for the skill runner."""

from pathlib import Path

import pytest

from cambium.models.event import Event
from cambium.models.routine import Routine
from cambium.models.skill import SkillRegistry
from cambium.runner.skill_runner import SkillRunner


class TestSkillRunner:
    def _setup(self, tmp_path: Path) -> tuple[SkillRegistry, Path]:
        """Create skill files and a prompt file, return registry and base dir."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        (skills_dir / "task-mgmt.md").write_text(
            "---\n"
            "name: task-mgmt\n"
            "description: Task management\n"
            "tools:\n"
            "  - clickup\n"
            "---\n"
            "# Task Management\n\nManage tasks.\n"
        )
        (skills_dir / "knowledge.md").write_text(
            "---\n"
            "name: knowledge\n"
            "description: Knowledge base\n"
            "tools:\n"
            "  - vault\n"
            "  - clickup\n"
            "---\n"
            "# Knowledge\n\nManage knowledge.\n"
        )

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "grooming.md").write_text("You are a grooming agent.\n")

        registry = SkillRegistry(skills_dir)
        return registry, tmp_path

    def _make_event(self) -> Event:
        return Event.create(type="task_queued", payload={"task_id": "123"}, source="test")

    def test_build_session_assembles_prompt(self, tmp_path: Path):
        registry, base = self._setup(tmp_path)
        runner = SkillRunner(registry)
        routine = Routine(
            name="grooming",
            prompt_path="prompts/grooming.md",
            skills=["task-mgmt", "knowledge"],
            subscribe=["task_queued"],
        )

        config = runner.build_session(routine, self._make_event(), prompt_base_dir=base)
        assert "You are a grooming agent." in config.prompt
        assert "Task Management" in config.prompt
        assert "Knowledge" in config.prompt
        assert config.routine_name == "grooming"

    def test_build_session_aggregates_tools_no_duplicates(self, tmp_path: Path):
        registry, base = self._setup(tmp_path)
        runner = SkillRunner(registry)
        routine = Routine(
            name="test",
            prompt_path="prompts/grooming.md",
            skills=["task-mgmt", "knowledge"],
            subscribe=[],
        )

        config = runner.build_session(routine, self._make_event(), prompt_base_dir=base)
        # clickup appears in both skills but should only appear once
        assert config.tools == ["clickup", "vault"]

    def test_build_session_missing_skill_raises(self, tmp_path: Path):
        registry, base = self._setup(tmp_path)
        runner = SkillRunner(registry)
        routine = Routine(
            name="test",
            prompt_path="",
            skills=["nonexistent"],
            subscribe=[],
        )

        with pytest.raises(ValueError, match="Missing skills: nonexistent"):
            runner.build_session(routine, self._make_event(), prompt_base_dir=base)

    def test_build_session_no_skills(self, tmp_path: Path):
        _, base = self._setup(tmp_path)
        runner = SkillRunner(SkillRegistry(base / "skills"))
        routine = Routine(
            name="simple",
            prompt_path="prompts/grooming.md",
            skills=[],
            subscribe=[],
        )

        config = runner.build_session(routine, self._make_event(), prompt_base_dir=base)
        assert "You are a grooming agent." in config.prompt
        assert config.tools == []

    def test_execute_returns_mock_result(self, tmp_path: Path):
        registry, base = self._setup(tmp_path)
        runner = SkillRunner(registry)
        routine = Routine(
            name="test",
            prompt_path="prompts/grooming.md",
            skills=["task-mgmt"],
            subscribe=[],
        )

        config = runner.build_session(routine, self._make_event(), prompt_base_dir=base)
        result = runner.execute(config)
        assert result.success is True
        assert "mock" in result.output
        assert result.events_emitted == []
