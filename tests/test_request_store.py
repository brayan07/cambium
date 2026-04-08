"""Tests for request store."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from cambium.request.model import Request, RequestStatus, RequestType
from cambium.request.store import RequestStore


def _make_request(
    type: RequestType = RequestType.PERMISSION,
    session_id: str = "sess-1",
    **kwargs,
) -> Request:
    return Request.create(
        session_id=session_id,
        type=type,
        summary=kwargs.pop("summary", "Do something?"),
        **kwargs,
    )


class TestCreateAndGet:
    def test_permission_round_trip(self):
        store = RequestStore()
        req = _make_request(RequestType.PERMISSION, summary="May I deploy?")
        store.create(req)
        got = store.get(req.id)
        assert got is not None
        assert got.id == req.id
        assert got.type == RequestType.PERMISSION
        assert got.status == RequestStatus.PENDING
        assert got.summary == "May I deploy?"
        assert got.answer is None
        assert got.answered_at is None

    def test_information_round_trip(self):
        store = RequestStore()
        req = _make_request(
            RequestType.INFORMATION,
            summary="What is the API key?",
            detail="Needed for deployment",
            work_item_id="wi-1",
            created_by="executor",
        )
        store.create(req)
        got = store.get(req.id)
        assert got.type == RequestType.INFORMATION
        assert got.detail == "Needed for deployment"
        assert got.work_item_id == "wi-1"
        assert got.created_by == "executor"

    def test_preference_round_trip(self):
        store = RequestStore()
        req = _make_request(
            RequestType.PREFERENCE,
            summary="Which color?",
            options=["red", "blue", "green"],
            default="blue",
            timeout_hours=24.0,
        )
        store.create(req)
        got = store.get(req.id)
        assert got.type == RequestType.PREFERENCE
        assert got.options == ["red", "blue", "green"]
        assert got.default == "blue"
        assert got.timeout_hours == 24.0

    def test_get_missing_returns_none(self):
        store = RequestStore()
        assert store.get("nonexistent") is None


class TestAnswer:
    def test_answer_pending(self):
        store = RequestStore()
        req = _make_request()
        store.create(req)

        result = store.answer(req.id, "yes")
        assert result.status == RequestStatus.ANSWERED
        assert result.answer == "yes"
        assert result.answered_at is not None

    def test_answer_non_pending_raises(self):
        store = RequestStore()
        req = _make_request()
        store.create(req)
        store.answer(req.id, "yes")

        with pytest.raises(ValueError, match="not pending"):
            store.answer(req.id, "no")

    def test_answer_rejected_raises(self):
        store = RequestStore()
        req = _make_request()
        store.create(req)
        store.reject(req.id)

        with pytest.raises(ValueError, match="not pending"):
            store.answer(req.id, "yes")

    def test_answer_expired_raises(self):
        store = RequestStore()
        req = _make_request(RequestType.PREFERENCE, timeout_hours=1.0)
        store.create(req)
        store.expire(req.id)

        with pytest.raises(ValueError, match="not pending"):
            store.answer(req.id, "yes")


class TestListRequests:
    def test_list_by_status(self):
        store = RequestStore()
        r1 = _make_request(summary="First")
        r2 = _make_request(summary="Second")
        store.create(r1)
        store.create(r2)
        store.answer(r1.id, "done")

        pending = store.list_requests(status=RequestStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == r2.id

        answered = store.list_requests(status=RequestStatus.ANSWERED)
        assert len(answered) == 1
        assert answered[0].id == r1.id

    def test_list_by_session_id(self):
        store = RequestStore()
        r1 = _make_request(session_id="sess-a")
        r2 = _make_request(session_id="sess-b")
        store.create(r1)
        store.create(r2)

        results = store.list_requests(session_id="sess-a")
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_list_by_created_by(self):
        store = RequestStore()
        r1 = _make_request(created_by="planner")
        r2 = _make_request(created_by="executor")
        store.create(r1)
        store.create(r2)

        results = store.list_requests(created_by="planner")
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_list_combined_filters(self):
        store = RequestStore()
        r1 = _make_request(session_id="s1", created_by="planner")
        r2 = _make_request(session_id="s1", created_by="executor")
        r3 = _make_request(session_id="s2", created_by="planner")
        store.create(r1)
        store.create(r2)
        store.create(r3)

        results = store.list_requests(session_id="s1", created_by="planner")
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_list_limit(self):
        store = RequestStore()
        for i in range(10):
            store.create(_make_request(summary=f"Req {i}"))
        results = store.list_requests(limit=3)
        assert len(results) == 3


class TestExpire:
    def test_expire_with_default(self):
        store = RequestStore()
        req = _make_request(
            RequestType.PREFERENCE,
            default="blue",
            timeout_hours=1.0,
        )
        store.create(req)
        store.expire(req.id)

        got = store.get(req.id)
        assert got.status == RequestStatus.EXPIRED
        assert got.answer == "blue"
        assert got.answered_at is not None

    def test_expire_without_default(self):
        store = RequestStore()
        req = _make_request(RequestType.PREFERENCE, timeout_hours=1.0)
        store.create(req)
        store.expire(req.id)

        got = store.get(req.id)
        assert got.status == RequestStatus.EXPIRED
        assert got.answer is None
        assert got.answered_at is None

    def test_expire_non_pending_raises(self):
        store = RequestStore()
        req = _make_request()
        store.create(req)
        store.answer(req.id, "yes")

        with pytest.raises(ValueError, match="not pending"):
            store.expire(req.id)


class TestReject:
    def test_reject_pending(self):
        store = RequestStore()
        req = _make_request()
        store.create(req)
        store.reject(req.id)

        got = store.get(req.id)
        assert got.status == RequestStatus.REJECTED

    def test_reject_non_pending_raises(self):
        store = RequestStore()
        req = _make_request()
        store.create(req)
        store.answer(req.id, "yes")

        with pytest.raises(ValueError, match="not pending"):
            store.reject(req.id)


class TestExpireOverdue:
    def test_expires_overdue_preference(self):
        store = RequestStore()
        # Create a preference request with a very short timeout
        req = _make_request(
            RequestType.PREFERENCE,
            summary="Pick a color",
            default="red",
            timeout_hours=0.001,  # ~3.6 seconds
        )
        # Backdate created_at to ensure it's overdue
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req.created_at = past
        store.create(req)

        count = store.expire_overdue()
        assert count == 1

        got = store.get(req.id)
        assert got.status == RequestStatus.EXPIRED
        assert got.answer == "red"

    def test_does_not_expire_non_overdue(self):
        store = RequestStore()
        req = _make_request(
            RequestType.PREFERENCE,
            timeout_hours=999.0,
        )
        store.create(req)

        count = store.expire_overdue()
        assert count == 0

        got = store.get(req.id)
        assert got.status == RequestStatus.PENDING

    def test_does_not_expire_permission_requests(self):
        store = RequestStore()
        req = _make_request(RequestType.PERMISSION, timeout_hours=0.001)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req.created_at = past
        store.create(req)

        count = store.expire_overdue()
        assert count == 0
        assert store.get(req.id).status == RequestStatus.PENDING

    def test_does_not_expire_information_requests(self):
        store = RequestStore()
        req = _make_request(RequestType.INFORMATION, timeout_hours=0.001)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req.created_at = past
        store.create(req)

        count = store.expire_overdue()
        assert count == 0
        assert store.get(req.id).status == RequestStatus.PENDING

    def test_skips_already_answered(self):
        store = RequestStore()
        req = _make_request(
            RequestType.PREFERENCE,
            timeout_hours=0.001,
        )
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req.created_at = past
        store.create(req)
        store.answer(req.id, "manual answer")

        count = store.expire_overdue()
        assert count == 0

    def test_expire_overdue_without_default(self):
        store = RequestStore()
        req = _make_request(
            RequestType.PREFERENCE,
            timeout_hours=0.001,
        )
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req.created_at = past
        store.create(req)

        count = store.expire_overdue()
        assert count == 1

        got = store.get(req.id)
        assert got.status == RequestStatus.EXPIRED
        assert got.answer is None
