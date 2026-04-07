"""Tests for eval config parsing and result models."""

import textwrap
from pathlib import Path

import pytest
import yaml

from cambium.eval.model import (
    Assertion,
    AssertionResult,
    EvalConfig,
    EvalResult,
    Injection,
    Scenario,
    ScenarioResult,
    TrialResult,
    WaitCondition,
    load_eval,
    load_config_override,
    merge_config_overrides,
)


class TestLoadEval:
    def test_basic_config(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            name: test-eval
            trials: 3
            timeout: 60
            scenarios:
              - name: basic
                inject:
                  channel: external_events
                  payload:
                    goal: "test"
                wait:
                  cascade_settled: true
                assertions:
                  - type: episode
                    routine: coordinator
                    status: completed
                  - type: no_errors
        """)
        path = tmp_path / "eval.yaml"
        path.write_text(config_yaml)

        config = load_eval(path)
        assert config.name == "test-eval"
        assert config.trials == 3
        assert config.timeout == 60
        assert len(config.scenarios) == 1

        scenario = config.scenarios[0]
        assert scenario.name == "basic"
        assert len(scenario.inject) == 1
        assert scenario.inject[0].channel == "external_events"
        assert scenario.inject[0].payload == {"goal": "test"}
        assert scenario.wait.cascade_settled is True
        assert len(scenario.assertions) == 2

    def test_multi_inject(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            name: multi
            scenarios:
              - name: multi-inject
                inject:
                  - channel: external_events
                    payload: {goal: "test1"}
                  - channel: heartbeat
                    payload: {target: sentry}
                    delay: 5.0
                wait:
                  cascade_settled: true
                assertions: []
        """)
        path = tmp_path / "eval.yaml"
        path.write_text(config_yaml)

        config = load_eval(path)
        scenario = config.scenarios[0]
        assert len(scenario.inject) == 2
        assert scenario.inject[0].channel == "external_events"
        assert scenario.inject[1].channel == "heartbeat"
        assert scenario.inject[1].delay == 5.0

    def test_defaults(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            name: minimal
            scenarios: []
        """)
        path = tmp_path / "eval.yaml"
        path.write_text(config_yaml)

        config = load_eval(path)
        assert config.trials == 5
        assert config.timeout == 180
        assert config.config_override == {}

    def test_config_override(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            name: with-override
            config_override:
              routines/coordinator.yaml:
                batch_window: 5
              adapters/claude-code/prompts/coordinator.md:
                append: "New line"
            scenarios: []
        """)
        path = tmp_path / "eval.yaml"
        path.write_text(config_yaml)

        config = load_eval(path)
        assert "routines/coordinator.yaml" in config.config_override
        assert config.config_override["routines/coordinator.yaml"]["batch_window"] == 5

    def test_wait_routine_completed(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            name: wait-test
            scenarios:
              - name: wait-routine
                inject:
                  channel: tasks
                  payload: {}
                wait:
                  routine_completed: executor
                assertions: []
        """)
        path = tmp_path / "eval.yaml"
        path.write_text(config_yaml)

        config = load_eval(path)
        assert config.scenarios[0].wait.routine_completed == "executor"
        assert config.scenarios[0].wait.cascade_settled is False

    def test_all_assertion_fields(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            name: assertions
            scenarios:
              - name: all-fields
                inject:
                  channel: external_events
                  payload: {}
                wait:
                  timeout_only: true
                assertions:
                  - type: llm_rubric
                    target: work_item.description
                    rubric: "Must be clear"
                    threshold: 0.7
                    weight: 0.5
        """)
        path = tmp_path / "eval.yaml"
        path.write_text(config_yaml)

        config = load_eval(path)
        a = config.scenarios[0].assertions[0]
        assert a.type == "llm_rubric"
        assert a.target == "work_item.description"
        assert a.rubric == "Must be clear"
        assert a.threshold == 0.7
        assert a.weight == 0.5


class TestConfigOverride:
    def test_load_override(self, tmp_path):
        override_yaml = textwrap.dedent("""\
            routines/coordinator.yaml:
              batch_window: 5
        """)
        path = tmp_path / "override.yaml"
        path.write_text(override_yaml)

        override = load_config_override(path)
        assert override["routines/coordinator.yaml"]["batch_window"] == 5

    def test_merge_overrides(self):
        base = {
            "routines/coordinator.yaml": {"batch_window": 10, "batch_max": 5},
            "timers.yaml": {"timers": []},
        }
        overlay = {
            "routines/coordinator.yaml": {"batch_window": 5},
            "new_file.yaml": {"key": "value"},
        }
        merged = merge_config_overrides(base, overlay)
        assert merged["routines/coordinator.yaml"]["batch_window"] == 5
        assert merged["routines/coordinator.yaml"]["batch_max"] == 5
        assert merged["timers.yaml"] == {"timers": []}
        assert merged["new_file.yaml"] == {"key": "value"}


class TestResultModels:
    def test_pass_rate(self):
        scenario = ScenarioResult(
            name="test",
            trials=[
                TrialResult(passed=True, duration=1.0),
                TrialResult(passed=True, duration=1.0),
                TrialResult(passed=False, duration=1.0),
            ],
        )
        assert abs(scenario.pass_rate - 2 / 3) < 0.01

    def test_pass_rate_empty(self):
        scenario = ScenarioResult(name="empty", trials=[])
        assert scenario.pass_rate == 0.0

    def test_overall_pass_rate(self):
        result = EvalResult(
            name="test",
            scenarios=[
                ScenarioResult(name="a", trials=[
                    TrialResult(passed=True, duration=1.0),
                ]),
                ScenarioResult(name="b", trials=[
                    TrialResult(passed=False, duration=1.0),
                ]),
            ],
        )
        assert result.overall_pass_rate == 0.5
