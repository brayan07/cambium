"""Integration tests for the metrics system — testing cross-component chains."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cambium.metric.model import (
    DeterministicMetric,
    IntelligentMetric,
    MetricType,
    Reading,
    SurveyMetric,
    load_metrics,
)
from cambium.metric.runner import MetricRunner
from cambium.metric.service import MetricService
from cambium.metric.store import ReadingStore
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.request.model import Request, RequestStatus, RequestType
from cambium.request.service import RequestService
from cambium.request.store import RequestStore
from cambium.runner.routine_runner import RoutineRunner


# ── Fixtures ─────────────────────────────────────────────────────────


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


def _make_runner(
    metrics, reading_store, request_service, queue, config_dir=None,
) -> MetricRunner:
    return MetricRunner(
        metrics=metrics,
        store=reading_store,
        request_service=request_service,
        queue=queue,
        config_dir=config_dir or Path("/tmp"),
    )


# ── Test 1: Full survey lifecycle ────────────────────────────────────


class TestSurveyLifecycle:
    """End-to-end: fire survey → user answers → reading recorded → visible via API."""

    def test_full_survey_flow(self, reading_store, request_service, queue) -> None:
        metric = SurveyMetric(
            name="weekly_productivity", type=MetricType.SURVEY,
            description="Weekly productivity rating", unit="score_1_5",
            tags=["wellbeing"], schedule="* * * * *",
            survey_summary="Rate your productivity (1-5)",
            survey_options=["1", "2", "3", "4", "5"],
            survey_detail="1=very low, 5=very high",
        )
        service = MetricService(
            store=reading_store, queue=queue, metrics=[metric],
        )
        runner = _make_runner([metric], reading_store, request_service, queue)

        # Step 1: Runner fires the survey
        runner.tick()

        # Verify SURVEY request was created
        requests = request_service.store.list_requests(type=RequestType.SURVEY)
        assert len(requests) == 1
        req = requests[0]
        assert req.type == RequestType.SURVEY
        assert req.summary == "Rate your productivity (1-5)"
        assert req.status == RequestStatus.PENDING

        # Step 2: User answers the survey
        request_service.answer_request(req.id, "4")

        # Step 3: Runner processes the answered survey
        runner.tick()

        # Step 4: Verify reading was recorded
        readings = reading_store.list_readings("weekly_productivity")
        assert len(readings) == 1
        assert readings[0].value == 4.0
        assert readings[0].source == f"survey:{req.id}"

        # Step 5: Verify visible via service (API layer)
        api_readings = service.list_readings("weekly_productivity")
        assert len(api_readings) == 1
        assert api_readings[0].value == 4.0

        summary = service.get_summary("weekly_productivity")
        assert summary["count"] == 1
        assert summary["latest_value"] == 4.0

    def test_survey_not_double_recorded(self, reading_store, request_service, queue) -> None:
        """Answered survey produces exactly one reading, even after multiple ticks."""
        metric = SurveyMetric(
            name="test_survey", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="Test?", survey_options=["1", "2", "3"],
        )
        runner = _make_runner([metric], reading_store, request_service, queue)

        # Fire and answer
        runner.tick()
        req = request_service.store.list_requests(type=RequestType.SURVEY)[0]
        request_service.store.answer(req.id, "2")

        # Process multiple times
        runner.tick()
        runner.tick()
        runner.tick()

        assert len(reading_store.list_readings("test_survey")) == 1


# ── Test 2: Full deterministic lifecycle via consumer ────────────────


class TestDeterministicLifecycle:
    """End-to-end: timer → consumer → runner → script → reading → API."""

    def test_consumer_dispatches_to_runner(
        self, reading_store, request_service, queue, tmp_path,
    ) -> None:
        # Create a test script
        script = tmp_path / "test.sh"
        script.write_text('#!/bin/bash\necho \'{"value": 0.87, "detail": "87% answer rate"}\'')
        script.chmod(0o755)

        metric = DeterministicMetric(
            name="answer_rate", type=MetricType.DETERMINISTIC,
            description="", unit="ratio", tags=["health"],
            schedule="* * * * *",
            script_path=str(script.relative_to(tmp_path)),
        )
        service = MetricService(
            store=reading_store, queue=queue, metrics=[metric],
        )
        runner = _make_runner(
            [metric], reading_store, request_service, queue, config_dir=tmp_path,
        )

        # Simulate what the timer + consumer do: publish heartbeat, then dispatch
        queue.publish(Message.create(
            channel="heartbeat",
            payload={"target": "metric-runner"},
            source="timer:metric-runner",
        ))

        # Create a minimal consumer with metric_runner
        consumer = ConsumerLoop(
            queue=queue,
            routine_registry=RoutineRegistry(),  # empty — no LLM routines
            routine_runner=None,  # not needed for metric-runner dispatch
            metric_runner=runner,
        )
        consumer.tick()

        # Verify reading was stored
        readings = reading_store.list_readings("answer_rate")
        assert len(readings) == 1
        assert readings[0].value == 0.87
        assert readings[0].source == "script"

        # Verify visible via service
        summary = service.get_summary("answer_rate")
        assert summary["count"] == 1
        assert summary["latest_value"] == 0.87

    def test_script_failure_does_not_crash_runner(
        self, reading_store, request_service, queue, tmp_path,
    ) -> None:
        """A failing script should log an error but not prevent other metrics from running."""
        bad_script = tmp_path / "bad.sh"
        bad_script.write_text("#!/bin/bash\nexit 1")
        bad_script.chmod(0o755)

        good_script = tmp_path / "good.sh"
        good_script.write_text('#!/bin/bash\necho \'{"value": 1.0, "detail": "ok"}\'')
        good_script.chmod(0o755)

        bad_metric = DeterministicMetric(
            name="bad", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="bad.sh",
        )
        good_metric = DeterministicMetric(
            name="good", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="good.sh",
        )
        runner = _make_runner(
            [bad_metric, good_metric], reading_store, request_service, queue,
            config_dir=tmp_path,
        )
        runner.tick()

        # Bad metric has no reading, good metric does
        assert len(reading_store.list_readings("bad")) == 0
        assert len(reading_store.list_readings("good")) == 1


# ── Test 3: Intelligent metric dispatch routing ──────────────────────


class TestIntelligentDispatchRouting:
    """Verify MetricRunner publishes to correct instance via target field."""

    def test_routes_to_correct_instance(self, reading_store, request_service, queue) -> None:
        light = IntelligentMetric(
            name="simple_check", type=MetricType.INTELLIGENT,
            description="", unit="score_0_1", tags=[], schedule="* * * * *",
            instance="metric-analyst",
        )
        heavy = IntelligentMetric(
            name="goal_progress", type=MetricType.INTELLIGENT,
            description="", unit="score_0_1", tags=[], schedule="* * * * *",
            instance="metric-analyst-heavy",
        )
        runner = _make_runner(
            [light, heavy], reading_store, request_service, queue,
        )
        runner._dispatch_due_intelligent(datetime.now(timezone.utc))

        messages = queue.consume(["metric_collect"], limit=10)
        assert len(messages) == 2

        by_target = {m.payload["target"]: m.payload["metrics"] for m in messages}
        assert by_target["metric-analyst"] == ["simple_check"]
        assert by_target["metric-analyst-heavy"] == ["goal_progress"]

    def test_no_dispatch_when_not_due(self, reading_store, request_service, queue) -> None:
        """Intelligent metrics that already ran recently should not be dispatched."""
        metric = IntelligentMetric(
            name="goal_progress", type=MetricType.INTELLIGENT,
            description="", unit="score_0_1", tags=[], schedule="0 6 * * *",
            instance="metric-analyst-heavy",
        )
        # Record a reading just now — so it's not due
        reading_store.record_reading(
            Reading.create(metric_name="goal_progress", value=0.5, source="metric-analyst")
        )
        runner = _make_runner(
            [metric], reading_store, request_service, queue,
        )
        runner._dispatch_due_intelligent(datetime.now(timezone.utc))

        messages = queue.consume(["metric_collect"], limit=10)
        assert len(messages) == 0


# ── Test 4: Config lifecycle — orphan detection ──────────────────────


class TestConfigLifecycle:
    def test_orphan_detection(self, reading_store) -> None:
        """Readings for removed metrics are detected as orphans."""
        # Record readings for two metrics
        reading_store.record_reading(
            Reading.create(metric_name="active_metric", value=1.0, source="s")
        )
        reading_store.record_reading(
            Reading.create(metric_name="removed_metric", value=2.0, source="s")
        )

        # Only "active_metric" is in the current config
        orphans = reading_store.get_orphaned_metric_names({"active_metric"})
        assert orphans == ["removed_metric"]

    def test_api_rejects_orphaned_metric(self, reading_store, queue) -> None:
        """Service refuses to serve readings for metrics not in current config."""
        # Record an orphaned reading directly in the store
        reading_store.record_reading(
            Reading.create(metric_name="orphan", value=1.0, source="s")
        )

        # Service only knows about "active"
        active = DeterministicMetric(
            name="active", type=MetricType.DETERMINISTIC,
            description="", unit="", tags=[], schedule="* * * * *",
            script_path="test.sh",
        )
        service = MetricService(store=reading_store, queue=queue, metrics=[active])

        # Orphan is invisible via service
        with pytest.raises(ValueError, match="Unknown metric"):
            service.list_readings("orphan")

        # Active metric works fine
        assert service.list_readings("active") == []

    def test_yaml_reload_picks_up_new_metric(self, tmp_path) -> None:
        """Adding a metric to YAML makes it available after reload."""
        yaml_v1 = "metrics:\n  - name: m1\n    type: deterministic\n    script_path: t.sh\n    schedule: '* * * * *'\n"
        yaml_v2 = yaml_v1 + "  - name: m2\n    type: intelligent\n    schedule: '0 6 * * *'\n"

        path = tmp_path / "metrics.yaml"
        path.write_text(yaml_v1)
        assert len(load_metrics(path)) == 1

        path.write_text(yaml_v2)
        assert len(load_metrics(path)) == 2


# ── Test 5: Survey expiry ────────────────────────────────────────────


class TestSurveyExpiry:
    def test_expired_survey_produces_no_reading(
        self, reading_store, request_service, queue,
    ) -> None:
        """When a survey request expires, no reading should be recorded."""
        metric = SurveyMetric(
            name="weekly_test", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="Test?", survey_options=["1", "2", "3"],
        )
        runner = _make_runner([metric], reading_store, request_service, queue)

        # Fire survey
        runner._fire_due_surveys(datetime.now(timezone.utc))
        requests = request_service.store.list_requests(type=RequestType.SURVEY)
        assert len(requests) == 1

        # Expire it (simulate timeout)
        request_service.store.expire(requests[0].id)

        # Process — should NOT record a reading for expired surveys
        runner._process_answered_surveys()
        assert len(reading_store.list_readings("weekly_test")) == 0

    def test_survey_expiry_sweep_covers_survey_type(self) -> None:
        """expire_overdue() handles SURVEY requests, not just PREFERENCE."""
        store = RequestStore(":memory:")

        # Create a SURVEY request with a very short timeout
        req = Request.create(
            session_id="test",
            type=RequestType.SURVEY,
            summary="Quick survey",
            timeout_hours=0.0001,  # ~0.36 seconds
        )
        store.create(req)

        # Wait a moment and sweep
        import time
        time.sleep(0.5)
        count = store.expire_overdue()
        assert count == 1

        expired = store.get(req.id)
        assert expired.status == RequestStatus.EXPIRED


# ── Test 6: Mixed tick — all three types in one cycle ────────────────


class TestMixedTick:
    def test_tick_handles_all_types(
        self, reading_store, request_service, queue, tmp_path,
    ) -> None:
        """A single tick() processes deterministic, survey, and intelligent metrics."""
        script = tmp_path / "test.sh"
        script.write_text('#!/bin/bash\necho \'{"value": 0.9, "detail": "ok"}\'')
        script.chmod(0o755)

        det = DeterministicMetric(
            name="det", type=MetricType.DETERMINISTIC,
            description="", unit="ratio", tags=[], schedule="* * * * *",
            script_path="test.sh",
        )
        survey = SurveyMetric(
            name="surv", type=MetricType.SURVEY,
            description="", unit="score_1_5", tags=[], schedule="* * * * *",
            survey_summary="Rate?", survey_options=["1", "2", "3"],
        )
        intel = IntelligentMetric(
            name="intel", type=MetricType.INTELLIGENT,
            description="", unit="score_0_1", tags=[], schedule="* * * * *",
            instance="metric-analyst-heavy",
        )
        runner = _make_runner(
            [det, survey, intel], reading_store, request_service, queue,
            config_dir=tmp_path,
        )

        runner.tick()

        # Deterministic: reading recorded
        assert len(reading_store.list_readings("det")) == 1

        # Survey: SURVEY request created
        surveys = request_service.store.list_requests(type=RequestType.SURVEY)
        assert len(surveys) == 1
        assert reading_store.get_metric_for_request(surveys[0].id) == "surv"

        # Intelligent: message published to metric_collect
        messages = queue.consume(["metric_collect"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload["target"] == "metric-analyst-heavy"
        assert messages[0].payload["metrics"] == ["intel"]
