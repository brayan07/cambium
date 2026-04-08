"""Tests for metric model — YAML loading and config parsing."""

import tempfile
from pathlib import Path

import pytest

from cambium.metric.model import (
    DeterministicMetric,
    IntelligentMetric,
    MetricConfig,
    MetricType,
    Reading,
    SurveyMetric,
    load_metrics,
)


SAMPLE_YAML = """\
metrics:
  - name: test_deterministic
    type: deterministic
    description: "Test metric"
    unit: ratio
    tags: [health]
    script_path: scripts/test.sh
    schedule: "0 */6 * * *"

  - name: test_survey
    type: survey
    description: "Test survey"
    unit: score_1_5
    tags: [wellbeing]
    survey_summary: "How are you?"
    survey_options: ["1", "2", "3", "4", "5"]
    survey_detail: "1=bad, 5=great"
    schedule: "0 18 * * 0"

  - name: test_intelligent
    type: intelligent
    description: "Test intelligent"
    unit: score_0_1
    tags: [alignment]
    schedule: "0 6 * * *"
    instance: metric-analyst-heavy
"""


class TestLoadMetrics:
    def test_loads_all_types(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.yaml"
        path.write_text(SAMPLE_YAML)
        metrics = load_metrics(path)
        assert len(metrics) == 3

    def test_deterministic_type(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.yaml"
        path.write_text(SAMPLE_YAML)
        metrics = load_metrics(path)
        det = [m for m in metrics if m.name == "test_deterministic"][0]
        assert isinstance(det, DeterministicMetric)
        assert det.type == MetricType.DETERMINISTIC
        assert det.script_path == "scripts/test.sh"
        assert det.schedule == "0 */6 * * *"
        assert det.tags == ["health"]

    def test_survey_type(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.yaml"
        path.write_text(SAMPLE_YAML)
        metrics = load_metrics(path)
        surv = [m for m in metrics if m.name == "test_survey"][0]
        assert isinstance(surv, SurveyMetric)
        assert surv.survey_summary == "How are you?"
        assert surv.survey_options == ["1", "2", "3", "4", "5"]
        assert surv.survey_detail == "1=bad, 5=great"

    def test_intelligent_type(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.yaml"
        path.write_text(SAMPLE_YAML)
        metrics = load_metrics(path)
        intel = [m for m in metrics if m.name == "test_intelligent"][0]
        assert isinstance(intel, IntelligentMetric)
        assert intel.instance == "metric-analyst-heavy"

    def test_intelligent_default_instance(self, tmp_path: Path) -> None:
        yaml_text = """\
metrics:
  - name: test
    type: intelligent
    schedule: "0 6 * * *"
"""
        path = tmp_path / "metrics.yaml"
        path.write_text(yaml_text)
        metrics = load_metrics(path)
        assert isinstance(metrics[0], IntelligentMetric)
        assert metrics[0].instance == "metric-analyst"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.yaml"
        assert load_metrics(path) == []

    def test_empty_yaml_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.yaml"
        path.write_text("")
        assert load_metrics(path) == []

    def test_invalid_type_skipped(self, tmp_path: Path) -> None:
        yaml_text = """\
metrics:
  - name: bad
    type: nonexistent
    schedule: "* * * * *"
  - name: good
    type: deterministic
    script_path: test.sh
    schedule: "* * * * *"
"""
        path = tmp_path / "metrics.yaml"
        path.write_text(yaml_text)
        metrics = load_metrics(path)
        assert len(metrics) == 1
        assert metrics[0].name == "good"

    def test_missing_schedule_skipped(self, tmp_path: Path) -> None:
        yaml_text = """\
metrics:
  - name: no_schedule
    type: deterministic
    script_path: test.sh
"""
        path = tmp_path / "metrics.yaml"
        path.write_text(yaml_text)
        metrics = load_metrics(path)
        assert len(metrics) == 0


class TestReadingCreate:
    def test_create_reading(self) -> None:
        r = Reading.create(
            metric_name="test",
            value=0.75,
            detail="test detail",
            source="test",
        )
        assert r.metric_name == "test"
        assert r.value == 0.75
        assert r.detail == "test detail"
        assert r.source == "test"
        assert r.id  # UUID generated
        assert r.recorded_at  # timestamp generated


class TestDefaultMetricsYaml:
    """Validate the shipped defaults/metrics.yaml file."""

    def test_loads_successfully(self) -> None:
        path = Path(__file__).parent.parent / "defaults" / "metrics.yaml"
        metrics = load_metrics(path)
        assert len(metrics) == 5

    def test_all_have_schedules(self) -> None:
        path = Path(__file__).parent.parent / "defaults" / "metrics.yaml"
        metrics = load_metrics(path)
        for m in metrics:
            assert m.schedule, f"Metric {m.name} has no schedule"

    def test_names_are_unique(self) -> None:
        path = Path(__file__).parent.parent / "defaults" / "metrics.yaml"
        metrics = load_metrics(path)
        names = [m.name for m in metrics]
        assert len(names) == len(set(names))

    def test_deterministic_have_script_paths(self) -> None:
        path = Path(__file__).parent.parent / "defaults" / "metrics.yaml"
        metrics = load_metrics(path)
        for m in metrics:
            if isinstance(m, DeterministicMetric):
                assert m.script_path, f"Deterministic metric {m.name} has no script_path"

    def test_survey_have_summaries(self) -> None:
        path = Path(__file__).parent.parent / "defaults" / "metrics.yaml"
        metrics = load_metrics(path)
        for m in metrics:
            if isinstance(m, SurveyMetric):
                assert m.survey_summary, f"Survey metric {m.name} has no survey_summary"
                assert m.survey_options, f"Survey metric {m.name} has no survey_options"
