"""Eval config data model — parsed from YAML eval definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# --- Config models (parsed from eval YAML) ---


@dataclass
class Injection:
    """A message to inject into a channel."""

    channel: str
    payload: dict = field(default_factory=dict)
    delay: float = 0.0  # seconds to wait before injecting


@dataclass
class WaitCondition:
    """How to determine when a scenario has completed."""

    routine_completed: str | None = None
    cascade_settled: bool = False
    timeout_only: bool = False


@dataclass
class Assertion:
    """A single assertion to check after a scenario runs."""

    type: str
    # Common fields — each assertion type uses a subset
    routine: str | None = None
    status: str | None = None
    channel: str | None = None
    title_contains: str | None = None
    target: str | None = None
    rubric: str | None = None
    threshold: float | None = None
    path: str | None = None
    pattern: str | None = None
    skill_dir: str | None = None
    preset: str | None = None
    min: int | None = None
    max: int | None = None
    weight: float = 1.0


@dataclass
class Scenario:
    """A single test scenario: inject, wait, assert."""

    name: str
    inject: list[Injection]
    wait: WaitCondition
    assertions: list[Assertion]


@dataclass
class EvalConfig:
    """Top-level eval configuration parsed from YAML."""

    name: str
    trials: int = 5
    timeout: int = 180
    config_override: dict[str, Any] = field(default_factory=dict)
    scenarios: list[Scenario] = field(default_factory=list)


# --- Result models ---


@dataclass
class AssertionResult:
    """Result of a single assertion check."""

    assertion: Assertion
    passed: bool
    detail: str = ""
    score: float | None = None  # 0.0-1.0 for scored assertions


@dataclass
class TrialResult:
    """Result of a single trial of a scenario."""

    passed: bool
    assertion_results: list[AssertionResult] = field(default_factory=list)
    duration: float = 0.0
    error: str | None = None


@dataclass
class ScenarioResult:
    """Aggregated results across all trials of a scenario."""

    name: str
    trials: list[TrialResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for t in self.trials if t.passed) / len(self.trials)


@dataclass
class EvalResult:
    """Top-level eval results."""

    name: str
    scenarios: list[ScenarioResult] = field(default_factory=list)

    @property
    def overall_pass_rate(self) -> float:
        if not self.scenarios:
            return 0.0
        return sum(s.pass_rate for s in self.scenarios) / len(self.scenarios)


# --- YAML loading ---


def _parse_injection(raw: dict | list) -> list[Injection]:
    """Parse inject field — can be a single dict or list of dicts."""
    if isinstance(raw, dict):
        return [Injection(
            channel=raw["channel"],
            payload=raw.get("payload", {}),
            delay=raw.get("delay", 0.0),
        )]
    return [
        Injection(
            channel=item["channel"],
            payload=item.get("payload", {}),
            delay=item.get("delay", 0.0),
        )
        for item in raw
    ]


def _parse_wait(raw: dict) -> WaitCondition:
    """Parse wait condition from YAML."""
    return WaitCondition(
        routine_completed=raw.get("routine_completed"),
        cascade_settled=raw.get("cascade_settled", False),
        timeout_only=raw.get("timeout_only", False),
    )


def _parse_assertion(raw: dict) -> Assertion:
    """Parse a single assertion from YAML."""
    return Assertion(
        type=raw["type"],
        routine=raw.get("routine"),
        status=raw.get("status"),
        channel=raw.get("channel"),
        title_contains=raw.get("title_contains"),
        target=raw.get("target"),
        rubric=raw.get("rubric"),
        threshold=raw.get("threshold"),
        path=raw.get("path"),
        pattern=raw.get("pattern"),
        skill_dir=raw.get("skill_dir"),
        preset=raw.get("preset"),
        min=raw.get("min"),
        max=raw.get("max"),
        weight=raw.get("weight", 1.0),
    )


def _parse_scenario(raw: dict) -> Scenario:
    """Parse a single scenario from YAML."""
    return Scenario(
        name=raw["name"],
        inject=_parse_injection(raw["inject"]),
        wait=_parse_wait(raw["wait"]),
        assertions=[_parse_assertion(a) for a in raw.get("assertions", [])],
    )


def load_eval(path: Path) -> EvalConfig:
    """Load an eval config from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    return EvalConfig(
        name=raw["name"],
        trials=raw.get("trials", 5),
        timeout=raw.get("timeout", 180),
        config_override=raw.get("config_override", {}),
        scenarios=[_parse_scenario(s) for s in raw.get("scenarios", [])],
    )


def load_config_override(path: Path) -> dict[str, Any]:
    """Load a config override YAML file (used with --config-override CLI flag)."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def merge_config_overrides(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two config override dicts. Overlay values win on conflict."""
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_config_overrides(merged[key], value)
        else:
            merged[key] = value
    return merged
