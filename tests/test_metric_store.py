"""Tests for metric reading store."""

import pytest

from cambium.metric.model import Reading
from cambium.metric.store import ReadingStore


@pytest.fixture
def store() -> ReadingStore:
    return ReadingStore(":memory:")


class TestRecordReading:
    def test_record_and_retrieve(self, store: ReadingStore) -> None:
        r = Reading.create(metric_name="test", value=0.5, detail="ok", source="script")
        store.record_reading(r)
        readings = store.list_readings("test")
        assert len(readings) == 1
        assert readings[0].id == r.id
        assert readings[0].value == 0.5

    def test_list_by_metric_name(self, store: ReadingStore) -> None:
        store.record_reading(Reading.create(metric_name="a", value=1.0, source="s"))
        store.record_reading(Reading.create(metric_name="b", value=2.0, source="s"))
        store.record_reading(Reading.create(metric_name="a", value=3.0, source="s"))
        assert len(store.list_readings("a")) == 2
        assert len(store.list_readings("b")) == 1

    def test_list_with_limit(self, store: ReadingStore) -> None:
        for i in range(5):
            store.record_reading(Reading.create(metric_name="m", value=float(i), source="s"))
        assert len(store.list_readings("m", limit=3)) == 3

    def test_list_ordered_desc(self, store: ReadingStore) -> None:
        r1 = Reading.create(metric_name="m", value=1.0, source="s")
        r2 = Reading.create(metric_name="m", value=2.0, source="s")
        store.record_reading(r1)
        store.record_reading(r2)
        readings = store.list_readings("m")
        # Most recent first
        assert readings[0].value == 2.0
        assert readings[1].value == 1.0


class TestGetLatestReading:
    def test_returns_latest(self, store: ReadingStore) -> None:
        store.record_reading(Reading.create(metric_name="m", value=1.0, source="s"))
        store.record_reading(Reading.create(metric_name="m", value=2.0, source="s"))
        latest = store.get_latest_reading("m")
        assert latest is not None
        assert latest.value == 2.0

    def test_returns_none_when_empty(self, store: ReadingStore) -> None:
        assert store.get_latest_reading("nonexistent") is None


class TestGetSummary:
    def test_summary_stats(self, store: ReadingStore) -> None:
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            store.record_reading(Reading.create(metric_name="m", value=v, source="s"))
        summary = store.get_summary("m")
        assert summary["count"] == 5
        assert summary["min"] == 1.0
        assert summary["max"] == 5.0
        assert summary["avg"] == 3.0
        assert summary["latest_value"] == 5.0

    def test_empty_summary(self, store: ReadingStore) -> None:
        summary = store.get_summary("empty")
        assert summary["count"] == 0
        assert summary["min"] is None


class TestSurveyRequestTracking:
    def test_link_and_retrieve(self, store: ReadingStore) -> None:
        store.link_survey_request("req-123", "weekly_rating")
        assert store.get_metric_for_request("req-123") == "weekly_rating"

    def test_unknown_request_returns_none(self, store: ReadingStore) -> None:
        assert store.get_metric_for_request("unknown") is None

    def test_has_reading_for_source(self, store: ReadingStore) -> None:
        assert not store.has_reading_for_source("survey:req-1")
        store.record_reading(
            Reading.create(metric_name="m", value=3.0, source="survey:req-1")
        )
        assert store.has_reading_for_source("survey:req-1")


class TestOrphanDetection:
    def test_detects_orphans(self, store: ReadingStore) -> None:
        store.record_reading(Reading.create(metric_name="known", value=1.0, source="s"))
        store.record_reading(Reading.create(metric_name="orphan", value=2.0, source="s"))
        orphans = store.get_orphaned_metric_names({"known"})
        assert orphans == ["orphan"]

    def test_no_orphans(self, store: ReadingStore) -> None:
        store.record_reading(Reading.create(metric_name="known", value=1.0, source="s"))
        assert store.get_orphaned_metric_names({"known"}) == []
