"""Tests that ported skills from Marcus parse correctly."""

from pathlib import Path
from cambium.models.skill import SkillRegistry


DEFAULTS_DIR = Path(__file__).parent.parent / "defaults" / "skills"


class TestPortedSkills:
    def test_all_skills_parse(self) -> None:
        registry = SkillRegistry(DEFAULTS_DIR)
        assert len(registry._skills) >= 5

    def test_excalidraw_has_frontmatter(self) -> None:
        registry = SkillRegistry(DEFAULTS_DIR)
        skill = registry.get("excalidraw-diagram")
        assert skill is not None
        assert skill.description != ""

    def test_skill_creator_has_frontmatter(self) -> None:
        registry = SkillRegistry(DEFAULTS_DIR)
        skill = registry.get("skill-creator")
        assert skill is not None
        assert skill.description != ""

    def test_voice_is_genericized(self) -> None:
        registry = SkillRegistry(DEFAULTS_DIR)
        skill = registry.get("voice")
        assert skill is not None
        assert "echo voice at 1.15x" not in skill.content

    def test_all_skills_have_names(self) -> None:
        registry = SkillRegistry(DEFAULTS_DIR)
        for name, skill in registry._skills.items():
            assert skill.name, f"Skill {name} has no name"
