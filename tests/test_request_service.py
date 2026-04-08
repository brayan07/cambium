"""Tests for request service."""

import pytest

from cambium.queue.sqlite import SQLiteQueue
from cambium.request.model import RequestStatus, RequestType
from cambium.request.service import RequestService
from cambium.request.store import RequestStore


@pytest.fixture()
def service():
    store = RequestStore()
    queue = SQLiteQueue()
    return RequestService(store=store, queue=queue)


class TestCreateRequest:
    def test_creates_and_persists(self, service):
        req = service.create_request(
            session_id="sess-1",
            type=RequestType.PERMISSION,
            summary="Can I merge PR #17?",
            detail="Eval passed, 3 files changed.",
            created_by="executor",
        )
        assert req.id is not None
        assert req.status == RequestStatus.PENDING
        assert req.summary == "Can I merge PR #17?"
        assert req.created_by == "executor"

        # Verify persisted
        got = service.get_request(req.id)
        assert got is not None
        assert got.summary == req.summary

    def test_publishes_to_input_needed(self, service):
        req = service.create_request(
            session_id="sess-1",
            type=RequestType.INFORMATION,
            summary="What is the API key?",
            created_by="executor",
        )
        # Check that a message was published to input_needed
        messages = service.queue.consume(["input_needed"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload["request_id"] == req.id
        assert messages[0].payload["type"] == "information"
        assert messages[0].payload["summary"] == "What is the API key?"


class TestAnswerRequest:
    def test_answer_updates_and_publishes_resume(self, service):
        req = service.create_request(
            session_id="sess-1",
            type=RequestType.PERMISSION,
            summary="Merge PR?",
            created_by="executor",
        )
        # Consume the input_needed message to clear the queue
        service.queue.consume(["input_needed"], limit=10)

        answered = service.answer_request(req.id, "approved")
        assert answered.status == RequestStatus.ANSWERED
        assert answered.answer == "approved"
        assert answered.answered_at is not None

        # Check resume message published
        messages = service.queue.consume(["resume"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload["user_response"] == req.id

    def test_answer_non_pending_raises(self, service):
        req = service.create_request(
            session_id="sess-1",
            type=RequestType.PERMISSION,
            summary="Merge PR?",
        )
        service.answer_request(req.id, "yes")
        with pytest.raises(ValueError, match="not pending"):
            service.answer_request(req.id, "yes again")


class TestRejectRequest:
    def test_reject_sets_status(self, service):
        req = service.create_request(
            session_id="sess-1",
            type=RequestType.PREFERENCE,
            summary="Research depth?",
            default="survey",
        )
        service.reject_request(req.id)
        got = service.get_request(req.id)
        assert got.status == RequestStatus.REJECTED


class TestListPending:
    def test_returns_only_pending(self, service):
        r1 = service.create_request(
            session_id="s1", type=RequestType.PERMISSION, summary="Q1",
        )
        r2 = service.create_request(
            session_id="s2", type=RequestType.INFORMATION, summary="Q2",
        )
        service.answer_request(r1.id, "yes")

        pending = service.list_pending()
        assert len(pending) == 1
        assert pending[0].id == r2.id


class TestGetSummary:
    def test_counts_by_type_and_status(self, service):
        service.create_request(
            session_id="s1", type=RequestType.PERMISSION, summary="Q1",
        )
        service.create_request(
            session_id="s2", type=RequestType.PERMISSION, summary="Q2",
        )
        service.create_request(
            session_id="s3", type=RequestType.PREFERENCE, summary="Q3",
            default="survey",
        )

        summary = service.get_summary()
        assert summary["permission"]["pending"] == 2
        assert summary["preference"]["pending"] == 1
