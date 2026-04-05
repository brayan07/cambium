"""Tests for skill, routine, message, and adapter instance models."""

from pathlib import Path

from cambium.models.skill import Skill, SkillRegistry
from cambium.models.message import Message
from cambium.models.routine import Routine, RoutineRegistry
from cambium.adapters.base import AdapterInstance, AdapterInstanceRegistry


class TestSkill:
    def test_from_dir_with_frontmatter(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: My Skill\n"
            "description: A test skill\n"
            "---\n"
            "# My Skill\n\nDo things.\n"
        )
        skill = Skill.from_dir(skill_dir)
        assert skill.name == "My Skill"
        assert skill.description == "A test skill"
        assert skill.dir_path == skill_dir.resolve()
        assert "# My Skill" in skill.content

    def test_from_dir_without_frontmatter(self, tmp_path: Path):
        skill_dir = tmp_path / "plain-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Plain Skill\n\nJust markdown.\n")
        skill = Skill.from_dir(skill_dir)
        assert skill.name == "plain-skill"
        assert skill.description == ""


class TestSkillRegistry:
    def test_loads_directory_skills(self, tmp_path: Path):
        for name in ["alpha", "beta"]:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n")
        reg = SkillRegistry(tmp_path)
        assert set(reg.names()) == {"alpha", "beta"}

    def test_user_dir_overrides_default(self, tmp_path: Path):
        default_dir = tmp_path / "default"
        user_dir = tmp_path / "user"
        default_dir.mkdir()
        user_dir.mkdir()
        d = default_dir / "shared"
        d.mkdir()
        (d / "SKILL.md").write_text("---\ndescription: default version\n---\n# Shared\n")
        u = user_dir / "shared"
        u.mkdir()
        (u / "SKILL.md").write_text("---\ndescription: user version\n---\n# Shared\n")
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

    def test_ignores_dirs_without_skill_md(self, tmp_path: Path):
        (tmp_path / "not-a-skill").mkdir()
        reg = SkillRegistry(tmp_path)
        assert reg.all() == []


class TestMessage:
    def test_create(self):
        msg = Message.create(channel="tasks", payload={"task": "test"}, source="coordinator")
        assert msg.channel == "tasks"
        assert msg.payload == {"task": "test"}
        assert msg.source == "coordinator"
        assert msg.status == "pending"
        assert len(msg.id) == 36


class TestRoutine:
    def test_from_file(self, tmp_path: Path):
        p = tmp_path / "coordinator.yaml"
        p.write_text(
            "name: coordinator\n"
            "adapter_instance: coordinator-agent\n"
            "listen:\n"
            "  - events\n"
            "publish:\n"
            "  - tasks\n"
            "  - plans\n"
        )
        r = Routine.from_file(p)
        assert r.name == "coordinator"
        assert r.adapter_instance == "coordinator-agent"
        assert r.listen == ["events"]
        assert r.publish == ["tasks", "plans"]

    def test_from_file_minimal(self, tmp_path: Path):
        p = tmp_path / "simple.yaml"
        p.write_text("name: simple\nadapter_instance: basic\n")
        r = Routine.from_file(p)
        assert r.name == "simple"
        assert r.listen == []
        assert r.publish == []


class TestRoutineRegistry:
    def _make_registry(self, tmp_path: Path) -> RoutineRegistry:
        (tmp_path / "a.yaml").write_text(
            "name: a\nadapter_instance: x\nlisten: [ch1, ch2]\n"
        )
        (tmp_path / "b.yaml").write_text(
            "name: b\nadapter_instance: y\nlisten: [ch2, ch3]\n"
        )
        return RoutineRegistry(tmp_path)

    def test_loads_routines(self, tmp_path: Path):
        reg = self._make_registry(tmp_path)
        assert len(reg.all()) == 2

    def test_for_channel(self, tmp_path: Path):
        reg = self._make_registry(tmp_path)
        assert len(reg.for_channel("ch1")) == 1
        assert len(reg.for_channel("ch2")) == 2
        assert len(reg.for_channel("ch3")) == 1

    def test_subscribed_channels(self, tmp_path: Path):
        reg = self._make_registry(tmp_path)
        assert sorted(reg.subscribed_channels()) == ["ch1", "ch2", "ch3"]

    def test_user_dir_overrides_default(self, tmp_path: Path):
        d = tmp_path / "default"
        u = tmp_path / "user"
        d.mkdir()
        u.mkdir()
        (d / "shared.yaml").write_text("name: shared\nadapter_instance: a\nlisten: [x]\n")
        (u / "shared.yaml").write_text("name: shared\nadapter_instance: b\nlisten: [y]\n")
        reg = RoutineRegistry(d, u)
        assert reg.get("shared").adapter_instance == "b"


class TestAdapterInstance:
    def test_from_file(self, tmp_path: Path):
        p = tmp_path / "coordinator.yaml"
        p.write_text(
            "name: coordinator\n"
            "adapter_type: claude-code\n"
            "config:\n"
            "  model: haiku\n"
            "  skills: [cambium-api]\n"
        )
        inst = AdapterInstance.from_file(p)
        assert inst.name == "coordinator"
        assert inst.adapter_type == "claude-code"
        assert inst.config["model"] == "haiku"
        assert inst.config["skills"] == ["cambium-api"]

    def test_from_file_minimal(self, tmp_path: Path):
        p = tmp_path / "basic.yaml"
        p.write_text("name: basic\nadapter_type: claude-code\n")
        inst = AdapterInstance.from_file(p)
        assert inst.name == "basic"
        assert inst.config == {}


class TestAdapterInstanceRegistry:
    def test_loads_instances(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text("name: a\nadapter_type: claude-code\n")
        (tmp_path / "b.yaml").write_text("name: b\nadapter_type: claude-code\n")
        reg = AdapterInstanceRegistry(tmp_path)
        assert len(reg.all()) == 2
        assert reg.get("a") is not None
        assert reg.get("missing") is None
