"""Skill data model and registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Skill:
    """A skill is a markdown file with optional YAML frontmatter."""

    name: str
    description: str
    path: Path
    content: str
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> Skill:
        """Parse a markdown skill file with optional YAML frontmatter."""
        text = path.read_text()
        frontmatter: dict = {}

        match = re.match(r"^---\n(.*?\n)---\n", text, re.DOTALL)
        if match:
            frontmatter = yaml.safe_load(match.group(1)) or {}

        return cls(
            name=frontmatter.get("name", path.stem),
            description=frontmatter.get("description", ""),
            path=path.resolve(),
            content=text,
            tools=frontmatter.get("tools", []),
            dependencies=frontmatter.get("dependencies", []),
        )


class SkillRegistry:
    """Loads skills from directories. User dir overrides defaults dir."""

    def __init__(self, *directories: Path) -> None:
        self._skills: dict[str, Skill] = {}
        # Later directories override earlier ones
        for d in directories:
            if d.is_dir():
                for f in sorted(d.glob("*.md")):
                    skill = Skill.from_file(f)
                    self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        """Return all loaded skills."""
        return list(self._skills.values())

    def names(self) -> list[str]:
        """Return all skill names."""
        return list(self._skills.keys())
