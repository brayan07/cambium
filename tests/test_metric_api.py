"""Tests for metric API endpoints."""

import pytest
from pathlib import Path

from cambium.metric.model import (
    DeterministicMetric,
    MetricType,
    Reading,
    SurveyMetric,
    IntelligentMetric,
)
from cambium.metric.service import MetricService
from cambium.metric.store import ReadingStore
from cambium.queue.sqlite import SQLiteQueue


@pytest.fixture
def store() -> ReadingStore:
    return ReadingStore(":memory:")


@pytest.fixture
def queue() -> SQLiteQueue:
    return SQLiteQueue(":memory:")


@pytest.fixture
def metrics():
    return [
        DeterministicMetric(
            name="det_metric", type=MetricType.DETERMINISTIC,
            description="Test det", unit="ratio", tags=["health"],
            schedule="0 * * * *", script_path="test.sh",
        ),
        SurveyMetric(
            name="survey_metric", type=MetricType.SURVEY,
            description="Test survey", unit="score_1_5", tags=["wellbeing"],
            schedule="0 18 * * 0", survey_summary="How?",
            survey_options=["1", "2", "3"], survey_detail="Rate",
        ),
        IntelligentMetric(
            name="intel_metric", type=MetricType.INTELLIGENT,
            description="Test intel", unit="score_0_1", tags=["alignment"],
            schedule="0 6 * * *", instance="metric-analyst-heavy",
        ),
    ]


@pytest.fixture
def service(store, queue, metrics) -> MetricService:
    return MetricService(store=store, queue=queue, metrics=metrics)


class TestMetricService:
    def test_get_metrics_all(self, service) -> None:
        assert len(service.get_metrics()) == 3

    def test_get_metrics_by_type(self, service) -> None:
        assert len(service.get_metrics(type="deterministic")) == 1
        assert len(service.get_metrics(type="survey")) == 1
        assert len(service.get_metrics(type="intelligent")) == 1

    def test_get_metrics_by_tag(self, service) -> None:
        assert len(service.get_metrics(tag="health")) == 1
        assert len(service.get_metrics(tag="wellbeing")) == 1

    def test_get_metric_by_name(self, service) -> None:
        m = service.get_metric("det_metric")
        assert m is not None
        assert m.name == "det_metric"

    def test_get_metric_not_found(self, service) -> None:
        assert service.get_metric("nonexistent") is None

    def test_record_reading(self, service) -> None:
        reading = service.record_reading(
            metric_name="det_metric",
            value=0.95,
            detail="test",
            source="test",
        )
        assert reading.value == 0.95

        # Verify it's in the store
        readings = service.list_readings("det_metric")
        assert len(readings) == 1

    def test_record_reading_unknown_metric_raises(self, service) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            service.record_reading(
                metric_name="nonexistent", value=1.0, source="test"
            )

    def test_record_reading_publishes(self, service, queue) -> None:
        service.record_reading(
            metric_name="det_metric", value=0.5, source="test"
        )
        messages = queue.consume(["metric_readings"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload["metric_name"] == "det_metric"
        assert messages[0].payload["value"] == 0.5

    def test_get_summary(self, service) -> None:
        for v in [1.0, 2.0, 3.0]:
            service.record_reading(
                metric_name="det_metric", value=v, source="test"
            )
        summary = service.get_summary("det_metric")
        assert summary["count"] == 3
        assert summary["avg"] == 2.0

    def test_list_readings_unknown_metric_raises(self, service) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            service.list_readings("nonexistent")


class TestRequestTypeSurvey:
    """Verify SURVEY request type exists and works."""

    def test_survey_type_exists(self) -> None:
        from cambium.request.model import RequestType
        assert RequestType.SURVEY == "survey"

    def test_survey_request_creation(self) -> None:
        from cambium.request.model import Request, RequestType
        req = Request.create(
            session_id="test",
            type=RequestType.SURVEY,
            summary="How are you?",
            options=["1", "2", "3", "4", "5"],
        )
        assert req.type == RequestType.SURVEY

    def test_request_store_type_filter(self) -> None:
        from cambium.request.model import RequestType
        from cambium.request.store import RequestStore

        store = RequestStore(":memory:")
        from cambium.request.model import Request

        req = Request.create(
            session_id="test", type=RequestType.SURVEY,
            summary="Survey test",
        )
        store.create(req)
        pref_req = Request.create(
            session_id="test", type=RequestType.PREFERENCE,
            summary="Pref test",
        )
        store.create(pref_req)

        surveys = store.list_requests(type=RequestType.SURVEY)
        assert len(surveys) == 1
        assert surveys[0].type == RequestType.SURVEY

        prefs = store.list_requests(type=RequestType.PREFERENCE)
        assert len(prefs) == 1
