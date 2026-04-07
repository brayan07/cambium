"""Tunable manifest — defines what the self-improvement loop can modify."""

from __future__ import annotations

from fnmatch import fnmatch as _fnmatch
from pathlib import PurePosixPath
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


def _path_match(path: str, pattern: str) -> bool:
    """Match a path against a glob pattern, segment-by-segment.

    Unlike fnmatch which treats * as matching / on some platforms,
    this matches each path segment independently so that
    "routines/*.yaml" does NOT match "routines/nested/deep.yaml".
    """
    path_parts = PurePosixPath(path).parts
    pattern_parts = PurePosixPath(pattern).parts

    if len(path_parts) != len(pattern_parts):
        return False

    return all(
        _fnmatch(p, pat) for p, pat in zip(path_parts, pattern_parts)
    )


@dataclass
class TunableEntry:
    """A file pattern that the system may propose changes to."""

    path: str
    type: str
    fields: list[str] | None = None


@dataclass
class ProtectedEntry:
    """A file that requires human authorship."""

    path: str


@dataclass
class TunableManifest:
    """Parsed tunable manifest with validation helpers."""

    tunable: list[TunableEntry] = field(default_factory=list)
    protected: list[ProtectedEntry] = field(default_factory=list)

    def is_tunable(self, path: str) -> bool:
        """Check if a file path matches any tunable pattern."""
        if self._is_protected(path):
            return False
        return any(_path_match(path, entry.path) for entry in self.tunable)

    def _is_protected(self, path: str) -> bool:
        """Check if a file path matches any protected pattern."""
        return any(_path_match(path, entry.path) for entry in self.protected)

    def get_tunable_entry(self, path: str) -> TunableEntry | None:
        """Get the tunable entry matching a path, if any."""
        if self._is_protected(path):
            return None
        for entry in self.tunable:
            if _path_match(path, entry.path):
                return entry
        return None

    def validate_override(self, config_override: dict[str, Any]) -> list[str]:
        """Validate a config override against the manifest.

        Returns a list of violation messages (empty = valid).
        """
        violations = []
        for file_path, override_value in config_override.items():
            if self._is_protected(file_path):
                violations.append(f"Protected file cannot be modified: {file_path}")
                continue

            entry = self.get_tunable_entry(file_path)
            if entry is None:
                violations.append(f"File not in tunable manifest: {file_path}")
                continue

            # For routine_config with restricted fields, check override keys
            if entry.fields and isinstance(override_value, dict):
                for key in override_value:
                    if key not in entry.fields:
                        violations.append(
                            f"Field '{key}' not tunable in {file_path} "
                            f"(allowed: {entry.fields})"
                        )

        return violations


def load_manifest(config_dir: Path) -> TunableManifest:
    """Load the tunable manifest from the config directory.

    Falls back to a permissive default if no manifest file exists.
    """
    manifest_path = config_dir / "tunable-manifest.yaml"
    if not manifest_path.exists():
        log.warning(f"No tunable manifest at {manifest_path}, using empty manifest")
        return TunableManifest()

    with open(manifest_path) as f:
        data = yaml.safe_load(f) or {}

    tunable = [
        TunableEntry(
            path=entry["path"],
            type=entry.get("type", "unknown"),
            fields=entry.get("fields"),
        )
        for entry in data.get("tunable", [])
    ]

    protected = [
        ProtectedEntry(path=entry["path"])
        for entry in data.get("protected", [])
    ]

    return TunableManifest(tunable=tunable, protected=protected)
