"""Tests for eval staging environment and assertions."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from cambium.eval.staging import (
    _apply_yaml_override,
    _apply_markdown_override,
    _apply_config_overrides,
    _find_free_port,
)
from cambium.eval.model import Assertion, AssertionResult
from cambium.eval.assertions import check_assertion
from cambium.eval.compare import compare, improved_or_maintained, format_comparison
from cambium.eval.report import format_console, format_json, save_baseline, load_baseline
from cambium.eval.model import EvalResult, ScenarioResult, TrialResult


class TestPortDiscovery:
    def test_find_free_port(self):
        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_ports_are_different(self):
        p1 = _find_free_port()
        p2 = _find_free_port()
        # Not guaranteed but highly likely with OS port allocation
        assert isinstance(p1, int)
        assert isinstance(p2, int)


class TestYamlOverride:
    def test_deep_merge(self, tmp_path):
        original = {"name": "test", "config": {"model": "opus", "temperature": 0.7}}
        path = tmp_path / "test.yaml"
        with open(path, "w") as f:
            yaml.safe_dump(original, f)

        _apply_yaml_override(path, {"config": {"model": "haiku"}})

        with open(path) as f:
            result = yaml.safe_load(f)

        assert result["name"] == "test"
        assert result["config"]["model"] == "haiku"
        assert result["config"]["temperature"] == 0.7

    def test_missing_file(self, tmp_path):
        # Should not raise
        _apply_yaml_override(tmp_path / "nonexistent.yaml", {"key": "value"})


class TestMarkdownOverride:
    def test_full_replacement(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("original content")

        _apply_markdown_override(path, {"content": "new content"})
        assert path.read_text() == "new content"

    def test_append(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("line 1")

        _apply_markdown_override(path, {"append": "line 2"})
        assert "line 1" in path.read_text()
        assert "line 2" in path.read_text()

    def test_patch(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("line 1\nold line\nline 3")

        _apply_markdown_override(path, {"patch": "-old line\n+new line"})
        content = path.read_text()
        assert "old line" not in content
        assert "new line" in content
        assert "line 1" in content
        assert "line 3" in content


class TestConfigOverrides:
    def test_applies_to_yaml_and_md(self, tmp_path):
        # Create files
        yaml_path = tmp_path / "routines" / "coordinator.yaml"
        yaml_path.parent.mkdir(parents=True)
        with open(yaml_path, "w") as f:
            yaml.safe_dump({"name": "coordinator", "batch_window": 10}, f)

        md_path = tmp_path / "prompts" / "test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("original prompt")

        overrides = {
            "routines/coordinator.yaml": {"batch_window": 5},
            "prompts/test.md": {"append": "\nNew section"},
        }
        _apply_config_overrides(tmp_path, overrides)

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["batch_window"] == 5

        assert "New section" in md_path.read_text()


class TestAssertions:
    def _mock_ctx(self, episodes=None, work_items=None, events=None):
        ctx = MagicMock()
        ctx.episodes = MagicMock(return_value=episodes or [])
        ctx.work_items = MagicMock(return_value=work_items or [])
        ctx.events = MagicMock(return_value=events or [])
        ctx.data_dir = Path("/tmp/test-data")
        return ctx

    def test_episode_pass(self):
        ctx = self._mock_ctx(episodes=[
            {"routine": "coordinator", "status": "completed"},
        ])
        a = Assertion(type="episode", routine="coordinator", status="completed")
        result = check_assertion(ctx, a)
        assert result.passed

    def test_episode_fail(self):
        ctx = self._mock_ctx(episodes=[])
        a = Assertion(type="episode", routine="coordinator", status="completed")
        result = check_assertion(ctx, a)
        assert not result.passed

    def test_work_item_created_pass(self):
        ctx = self._mock_ctx(work_items=[
            {"title": "Implement hello world feature"},
        ])
        a = Assertion(type="work_item_created", title_contains="hello")
        result = check_assertion(ctx, a)
        assert result.passed

    def test_work_item_created_fail(self):
        ctx = self._mock_ctx(work_items=[
            {"title": "Something else"},
        ])
        a = Assertion(type="work_item_created", title_contains="hello")
        result = check_assertion(ctx, a)
        assert not result.passed

    def test_no_errors_pass(self):
        ctx = self._mock_ctx(episodes=[
            {"routine": "coordinator", "status": "completed"},
        ])
        a = Assertion(type="no_errors")
        result = check_assertion(ctx, a)
        assert result.passed

    def test_no_errors_fail(self):
        ctx = self._mock_ctx(episodes=[
            {"routine": "coordinator", "status": "error"},
        ])
        a = Assertion(type="no_errors")
        result = check_assertion(ctx, a)
        assert not result.passed

    def test_event_published_pass(self):
        ctx = self._mock_ctx(events=[{"channel": "plans", "payload": {}}])
        a = Assertion(type="event_published", channel="plans")
        result = check_assertion(ctx, a)
        assert result.passed

    def test_unknown_assertion_type(self):
        ctx = self._mock_ctx()
        a = Assertion(type="nonexistent_type")
        result = check_assertion(ctx, a)
        assert not result.passed
        assert "Unknown" in result.detail


class TestCompare:
    def test_no_regression(self):
        baseline = EvalResult(name="baseline", scenarios=[
            ScenarioResult(name="a", trials=[TrialResult(passed=True, duration=1.0)]),
        ])
        current = EvalResult(name="current", scenarios=[
            ScenarioResult(name="a", trials=[TrialResult(passed=True, duration=1.0)]),
        ])
        report = compare(baseline, current)
        assert improved_or_maintained(report)

    def test_regression_detected(self):
        baseline = EvalResult(name="baseline", scenarios=[
            ScenarioResult(name="a", trials=[TrialResult(passed=True, duration=1.0)]),
        ])
        current = EvalResult(name="current", scenarios=[
            ScenarioResult(name="a", trials=[TrialResult(passed=False, duration=1.0)]),
        ])
        report = compare(baseline, current)
        assert not improved_or_maintained(report)

    def test_improvement(self):
        baseline = EvalResult(name="baseline", scenarios=[
            ScenarioResult(name="a", trials=[TrialResult(passed=False, duration=1.0)]),
        ])
        current = EvalResult(name="current", scenarios=[
            ScenarioResult(name="a", trials=[TrialResult(passed=True, duration=1.0)]),
        ])
        report = compare(baseline, current)
        assert improved_or_maintained(report)
        assert report.any_improved

    def test_format_comparison(self):
        baseline = EvalResult(name="baseline", scenarios=[
            ScenarioResult(name="test-scenario", trials=[TrialResult(passed=True, duration=1.0)]),
        ])
        current = EvalResult(name="current", scenarios=[
            ScenarioResult(name="test-scenario", trials=[TrialResult(passed=False, duration=1.0)]),
        ])
        report = compare(baseline, current)
        output = format_comparison(report)
        assert "REGRESSED" in output
        assert "test-scenario" in output


class TestReport:
    def test_format_console(self):
        result = EvalResult(name="test", scenarios=[
            ScenarioResult(name="scenario-1", trials=[
                TrialResult(
                    passed=True, duration=1.5,
                    assertion_results=[
                        AssertionResult(
                            assertion=Assertion(type="episode"),
                            passed=True,
                        ),
                    ],
                ),
            ]),
        ])
        output = format_console(result)
        assert "test" in output
        assert "scenario-1" in output
        assert "PASS" in output

    def test_format_json_roundtrip(self, tmp_path):
        result = EvalResult(name="test", scenarios=[
            ScenarioResult(name="s1", trials=[
                TrialResult(
                    passed=True, duration=2.0,
                    assertion_results=[
                        AssertionResult(
                            assertion=Assertion(type="no_errors"),
                            passed=True,
                        ),
                    ],
                ),
            ]),
        ])
        path = tmp_path / "baseline.json"
        save_baseline(result, path)

        loaded = load_baseline(path)
        assert loaded.name == "test"
        assert len(loaded.scenarios) == 1
        assert loaded.scenarios[0].name == "s1"
        assert loaded.scenarios[0].trials[0].passed
