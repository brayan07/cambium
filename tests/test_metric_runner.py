"""Tests for MetricRunner — scheduling, execution, and dispatch."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cambium.metric.model import (
    DeterministicMetric,
    IntelligentMetric,
    MetricType,
    Reading,
    SurveyMetric,
)
from cambium.metric.runner import MetricRunner
from cambium.metric.store import ReadingStore
from cambium.request.model import Request, RequestStatus, RequestType
from cambium.request.service import RequestService
from cambium.request.store import RequestStore
from cambium.queue.sqlite import SQLiteQueue


@pytest.fixture
def queue() -> SQLiteQueue:
    return SQLiteQueue(":memory:")


@pytest.fixture
def request_store() -> RequestStore:
    return RequestStore(":memory:")


@pytest.fixture
def request_service(request_store, queue) -> RequestService:
    return RequestService(store=request_store, queue=queue)


@pytest.fixture
def reading_store() -> ReadingStore:
    return ReadingStore(":memory:")


class TestScheduling:
    def test_never_run_is_due(self, reading_store, request_service, queue) -> None:
        metric = DeterministicMetric(
            name="test", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="0 * * * *",
            script_path="test.sh",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        assert runner._is_due("test", "0 * * * *", datetime.now(timezone.utc))

    def test_recently_run_not_due(self, reading_store, request_service, queue) -> None:
        metric = DeterministicMetric(
            name="test", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="0 * * * *",
            script_path="test.sh",
        )
        # Record a reading just now
        reading_store.record_reading(
            Reading.create(metric_name="test", value=1.0, source="script")
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        # Should not be due within the same hour
        now = datetime.now(timezone.utc)
        assert not runner._is_due("test", "0 * * * *", now)


class TestDeterministicExecution:
    def test_execute_script(self, reading_store, request_service, queue, tmp_path) -> None:
        script = tmp_path / "test.sh"
        script.write_text('#!/bin/bash\necho \'{"value": 0.95, "detail": "test ok"}\'')
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="test_det", type=MetricType.DETERMINISTIC,
            description="", unit="ratio", tags=[], schedule="* * * * *",
            script_path=str(script.relative_to(tmp_path)),
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        result = runner._execute_script(metric)
        assert result["value"] == 0.95
        assert result["detail"] == "test ok"

    def test_run_records_reading(self, reading_store, request_service, queue, tmp_path) -> None:
        script = tmp_path / "test.sh"
        script.write_text('#!/bin/bash\necho \'{"value": 0.8, "detail": "good"}\'')
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="test_det", type=MetricType.DETERMINISTIC,
            description="", unit="ratio", tags=[], schedule="* * * * *",
            script_path=str(script.relative_to(tmp_path)),
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        runner._run_due_deterministic(datetime.now(timezone.utc))
        readings = reading_store.list_readings("test_det")
        assert len(readings) == 1
        assert readings[0].value == 0.8


class TestSurveyFiring:
    def test_fire_creates_request(self, reading_store, request_service, queue) -> None:
        metric = SurveyMetric(
            name="weekly_test", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="How are you?",
            survey_options=["1", "2", "3", "4", "5"],
            survey_detail="Rate yourself",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._fire_due_surveys(datetime.now(timezone.utc))

        # Check a SURVEY request was created
        requests = request_service.store.list_requests(type=RequestType.SURVEY)
        assert len(requests) == 1
        assert requests[0].summary == "How are you?"
        assert requests[0].type == RequestType.SURVEY

        # Check survey_request link was stored
        metric_name = reading_store.get_metric_for_request(requests[0].id)
        assert metric_name == "weekly_test"

    def test_process_answered_survey(self, reading_store, request_service, queue) -> None:
        metric = SurveyMetric(
            name="weekly_test", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="How are you?",
            survey_options=["1", "2", "3", "4", "5"],
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )

        # Fire the survey
        runner._fire_due_surveys(datetime.now(timezone.utc))
        requests = request_service.store.list_requests(type=RequestType.SURVEY)
        req_id = requests[0].id

        # Answer it
        request_service.store.answer(req_id, "4")

        # Process answered surveys
        runner._process_answered_surveys()

        # Check reading was recorded
        readings = reading_store.list_readings("weekly_test")
        assert len(readings) == 1
        assert readings[0].value == 4.0
        assert readings[0].source == f"survey:{req_id}"

    def test_dedup_prevents_double_recording(self, reading_store, request_service, queue) -> None:
        metric = SurveyMetric(
            name="weekly_test", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="How are you?",
            survey_options=["1", "2", "3"],
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._fire_due_surveys(datetime.now(timezone.utc))
        req_id = request_service.store.list_requests(type=RequestType.SURVEY)[0].id
        request_service.store.answer(req_id, "3")

        runner._process_answered_surveys()
        runner._process_answered_surveys()  # second call should be no-op

        assert len(reading_store.list_readings("weekly_test")) == 1


class TestScriptEdgeCases:
    """Edge cases for deterministic script execution."""

    def test_invalid_json_output(self, reading_store, request_service, queue, tmp_path) -> None:
        """Script that outputs non-JSON should fail gracefully."""
        script = tmp_path / "bad_json.sh"
        script.write_text("#!/bin/bash\necho 'not json at all'")
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="bad_json", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="bad_json.sh",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        # _execute_script should raise json.JSONDecodeError
        with pytest.raises(json.JSONDecodeError):
            runner._execute_script(metric)

    def test_invalid_json_does_not_record(self, reading_store, request_service, queue, tmp_path) -> None:
        """Script with bad JSON produces no reading but doesn't crash the runner."""
        script = tmp_path / "bad.sh"
        script.write_text("#!/bin/bash\necho '{broken'")
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="bad", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="bad.sh",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        # tick-level method catches exceptions
        runner._run_due_deterministic(datetime.now(timezone.utc))
        assert len(reading_store.list_readings("bad")) == 0

    def test_script_timeout(self, reading_store, request_service, queue, tmp_path) -> None:
        """Script that exceeds timeout raises subprocess.TimeoutExpired."""
        script = tmp_path / "slow.sh"
        script.write_text("#!/bin/bash\nsleep 60\necho '{\"value\": 1.0}'")
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="slow", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="slow.sh",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        import subprocess as sp
        with pytest.raises(sp.TimeoutExpired):
            runner._execute_script(metric)

    def test_nonzero_exit_raises(self, reading_store, request_service, queue, tmp_path) -> None:
        """Script exiting non-zero raises RuntimeError."""
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/bash\necho 'oops' >&2\nexit 2")
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="fail", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="fail.sh",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        with pytest.raises(RuntimeError, match="exited 2"):
            runner._execute_script(metric)

    def test_missing_script_raises(self, reading_store, request_service, queue, tmp_path) -> None:
        """Script path that doesn't exist raises FileNotFoundError."""
        metric = DeterministicMetric(
            name="missing", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="does_not_exist.sh",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=tmp_path,
        )
        with pytest.raises(FileNotFoundError):
            runner._execute_script(metric)


class TestSurveyAnswerEdgeCases:
    """Edge cases for survey response processing."""

    def test_non_numeric_answer_skipped(self, reading_store, request_service, queue) -> None:
        """Survey answer that isn't a number produces no reading."""
        metric = SurveyMetric(
            name="test_survey", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="Rate?", survey_options=["1", "2", "3"],
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._fire_due_surveys(datetime.now(timezone.utc))
        req = request_service.store.list_requests(type=RequestType.SURVEY)[0]
        request_service.store.answer(req.id, "not a number")

        runner._process_answered_surveys()
        assert len(reading_store.list_readings("test_survey")) == 0

    def test_empty_answer_skipped(self, reading_store, request_service, queue) -> None:
        """Empty survey answer produces no reading."""
        metric = SurveyMetric(
            name="test_survey", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="Rate?", survey_options=["1", "2", "3"],
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._fire_due_surveys(datetime.now(timezone.utc))
        req = request_service.store.list_requests(type=RequestType.SURVEY)[0]
        request_service.store.answer(req.id, "")

        runner._process_answered_surveys()
        assert len(reading_store.list_readings("test_survey")) == 0

    def test_float_answer_accepted(self, reading_store, request_service, queue) -> None:
        """Survey answer like '3.5' should be accepted as a float."""
        metric = SurveyMetric(
            name="test_survey", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="Rate?", survey_options=["1", "2", "3", "4", "5"],
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._fire_due_surveys(datetime.now(timezone.utc))
        req = request_service.store.list_requests(type=RequestType.SURVEY)[0]
        request_service.store.answer(req.id, "3.5")

        runner._process_answered_surveys()
        readings = reading_store.list_readings("test_survey")
        assert len(readings) == 1
        assert readings[0].value == 3.5


class TestIntelligentDispatch:
    def test_dispatch_publishes_to_channel(self, reading_store, request_service, queue) -> None:
        metric = IntelligentMetric(
            name="goal_progress", type=MetricType.INTELLIGENT,
            description="", unit="score_0_1", tags=[], schedule="* * * * *",
            instance="metric-analyst-heavy",
        )
        runner = MetricRunner(
            metrics=[metric], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._dispatch_due_intelligent(datetime.now(timezone.utc))

        # Check message was published
        messages = queue.consume(["metric_collect"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload["target"] == "metric-analyst-heavy"
        assert messages[0].payload["metrics"] == ["goal_progress"]

    def test_groups_by_instance(self, reading_store, request_service, queue) -> None:
        m1 = IntelligentMetric(
            name="m1", type=MetricType.INTELLIGENT,
            description="", unit="", tags=[], schedule="* * * * *",
            instance="metric-analyst",
        )
        m2 = IntelligentMetric(
            name="m2", type=MetricType.INTELLIGENT,
            description="", unit="", tags=[], schedule="* * * * *",
            instance="metric-analyst-heavy",
        )
        m3 = IntelligentMetric(
            name="m3", type=MetricType.INTELLIGENT,
            description="", unit="", tags=[], schedule="* * * * *",
            instance="metric-analyst",
        )
        runner = MetricRunner(
            metrics=[m1, m2, m3], store=reading_store,
            request_service=request_service, queue=queue,
            config_dir=Path("/tmp"),
        )
        runner._dispatch_due_intelligent(datetime.now(timezone.utc))

        messages = queue.consume(["metric_collect"], limit=10)
        assert len(messages) == 2

        payloads = {m.payload["target"]: m.payload["metrics"] for m in messages}
        assert set(payloads["metric-analyst"]) == {"m1", "m3"}
        assert payloads["metric-analyst-heavy"] == ["m2"]
