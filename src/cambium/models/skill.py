"""Skill data model and registry — Claude Code native skill format (directory with SKILL.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Skill:
    """A skill in Claude Code native format: a directory with SKILL.md."""

    name: str
    description: str
    dir_path: Path
    content: str  # Raw SKILL.md content (including frontmatter)

    @classmethod
    def from_dir(cls, dir_path: Path) -> Skill:
        """Load a skill from a directory containing SKILL.md."""
        skill_md = dir_path / "SKILL.md"
        text = skill_md.read_text()
        frontmatter = _parse_frontmatter(text)

        return cls(
            name=frontmatter.get("name", dir_path.name),
            description=frontmatter.get("description", ""),
            dir_path=dir_path.resolve(),
            content=text,
        )


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown text."""
    match = re.match(r"^---\n(.*?\n)---\n", text, re.DOTALL)
    if match:
        return yaml.safe_load(match.group(1)) or {}
    return {}


class SkillRegistry:
    """Loads skills from directories containing SKILL.md.

    User dir overrides defaults dir (later directories override earlier ones).
    """

    def __init__(self, *directories: Path) -> None:
        self._skills: dict[str, Skill] = {}
        for d in directories:
            if not d.is_dir():
                continue
            for subdir in sorted(d.iterdir()):
                if subdir.is_dir() and (subdir / "SKILL.md").exists():
                    skill = Skill.from_dir(subdir)
                    self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills.keys())
