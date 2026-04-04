"""Tests for skill and routine models."""

from pathlib import Path

from cambium.models.skill import Skill, SkillRegistry
from cambium.models.routine import Routine, RoutineRegistry


class TestSkill:
    def test_from_file_with_frontmatter(self, tmp_path: Path):
        p = tmp_path / "my-skill.md"
        p.write_text(
            "---\n"
            "name: My Skill\n"
            "description: A test skill\n"
            "tools:\n"
            "  - clickup\n"
            "  - github\n"
            "dependencies:\n"
            "  - other-skill\n"
            "---\n"
            "# My Skill\n\nDo things.\n"
        )
        skill = Skill.from_file(p)
        assert skill.name == "My Skill"
        assert skill.description == "A test skill"
        assert skill.tools == ["clickup", "github"]
        assert skill.dependencies == ["other-skill"]
        assert skill.path == p.resolve()
        assert "# My Skill" in skill.content

    def test_from_file_without_frontmatter(self, tmp_path: Path):
        p = tmp_path / "plain-skill.md"
        p.write_text("# Plain Skill\n\nJust markdown.\n")
        skill = Skill.from_file(p)
        assert skill.name == "plain-skill"
        assert skill.description == ""
        assert skill.tools == []
        assert skill.dependencies == []

    def test_from_file_empty_frontmatter(self, tmp_path: Path):
        p = tmp_path / "empty-fm.md"
        p.write_text("---\n---\n# Content\n")
        skill = Skill.from_file(p)
        assert skill.name == "empty-fm"
        assert skill.description == ""


class TestSkillRegistry:
    def test_loads_all_skills(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("# A\n")
        (tmp_path / "b.md").write_text("# B\n")
        reg = SkillRegistry(tmp_path)
        assert set(reg.names()) == {"a", "b"}

    def test_user_dir_overrides_default(self, tmp_path: Path):
        default_dir = tmp_path / "default"
        user_dir = tmp_path / "user"
        default_dir.mkdir()
        user_dir.mkdir()
        (default_dir / "shared.md").write_text(
            "---\ndescription: default version\n---\n# Shared\n"
        )
        (user_dir / "shared.md").write_text(
            "---\ndescription: user version\n---\n# Shared\n"
        )
        reg = SkillRegistry(default_dir, user_dir)
        skill = reg.get("shared")
        assert skill is not None
        assert skill.description == "user version"

    def test_get_missing_returns_none(self, tmp_path: Path):
        reg = SkillRegistry(tmp_path)
        assert reg.get("nonexistent") is None

    def test_ignores_nonexistent_directory(self):
        reg = SkillRegistry(Path("/nonexistent/dir"))
        assert reg.all() == []


class TestRoutine:
    def test_from_file(self, tmp_path: Path):
        p = tmp_path / "grooming.yaml"
        p.write_text(
            "name: grooming\n"
            "prompt_path: prompts/grooming.md\n"
            "skills:\n"
            "  - task-management\n"
            "  - knowledge-management\n"
            "subscribe:\n"
            "  - task_queued\n"
            "  - goal_created\n"
            "emit:\n"
            "  - task_groomed\n"
            "persistent: true\n"
            "session_key: grooming-main\n"
            "working_directory: /tmp/work\n"
        )
        r = Routine.from_file(p)
        assert r.name == "grooming"
        assert r.prompt_path == "prompts/grooming.md"
        assert r.skills == ["task-management", "knowledge-management"]
        assert r.subscribe == ["task_queued", "goal_created"]
        assert r.emit == ["task_groomed"]
        assert r.persistent is True
        assert r.session_key == "grooming-main"
        assert r.working_directory == "/tmp/work"

    def test_from_file_minimal(self, tmp_path: Path):
        p = tmp_path / "simple.yaml"
        p.write_text("prompt_path: prompts/simple.md\n")
        r = Routine.from_file(p)
        assert r.name == "simple"
        assert r.skills == []
        assert r.subscribe == []
        assert r.persistent is False


class TestRoutineRegistry:
    def test_loads_routines(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text("prompt_path: a.md\nsubscribe: [ev_a]\n")
        (tmp_path / "b.yml").write_text("prompt_path: b.md\nsubscribe: [ev_b]\n")
        reg = RoutineRegistry(tmp_path)
        assert len(reg.all()) == 2

    def test_for_event_type(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text("prompt_path: a.md\nsubscribe: [ev_a, ev_shared]\n")
        (tmp_path / "b.yaml").write_text("prompt_path: b.md\nsubscribe: [ev_b, ev_shared]\n")
        reg = RoutineRegistry(tmp_path)
        assert len(reg.for_event_type("ev_shared")) == 2
        assert len(reg.for_event_type("ev_a")) == 1
        assert len(reg.for_event_type("ev_none")) == 0

    def test_subscribed_event_types(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text("prompt_path: a.md\nsubscribe: [x, y]\n")
        (tmp_path / "b.yaml").write_text("prompt_path: b.md\nsubscribe: [y, z]\n")
        reg = RoutineRegistry(tmp_path)
        assert reg.subscribed_event_types() == ["x", "y", "z"]

    def test_user_dir_overrides_default(self, tmp_path: Path):
        default_dir = tmp_path / "default"
        user_dir = tmp_path / "user"
        default_dir.mkdir()
        user_dir.mkdir()
        (default_dir / "shared.yaml").write_text("prompt_path: default.md\n")
        (user_dir / "shared.yaml").write_text("prompt_path: user.md\n")
        reg = RoutineRegistry(default_dir, user_dir)
        r = reg.get("shared")
        assert r is not None
        assert r.prompt_path == "user.md"
