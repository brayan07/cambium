"""Tests that default skills parse correctly."""

from pathlib import Path
from cambium.models.skill import SkillRegistry


SKILLS_DIR = Path(__file__).parent.parent / "defaults" / "adapters" / "claude-code" / "skills"


class TestDefaultSkills:
    def test_cambium_api_skill_parses(self) -> None:
        registry = SkillRegistry(SKILLS_DIR)
        assert len(registry._skills) >= 1

    def test_cambium_api_has_frontmatter(self) -> None:
        registry = SkillRegistry(SKILLS_DIR)
        skill = registry.get("cambium-api")
        assert skill is not None
        assert skill.description != ""

    def test_all_skills_have_names(self) -> None:
        registry = SkillRegistry(SKILLS_DIR)
        for name, skill in registry._skills.items():
            assert skill.name, f"Skill {name} has no name"
