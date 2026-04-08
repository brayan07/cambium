"""Integration tests for the HITL protocol — Phase 1.

These tests exercise the full flow across real component instances
(queue, stores, services, consumer loop) with a fake adapter.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.adapters.base import AdapterInstanceRegistry, AdapterType, RunResult
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.request.model import RequestStatus, RequestType
from cambium.request.service import RequestService
from cambium.request.store import RequestStore
from cambium.runner.routine_runner import RoutineRunner
from cambium.server.app import CambiumServer, app, build_server
from cambium.server.auth import create_session_token
from cambium.session.model import Session, SessionOrigin, SessionStatus
from cambium.session.store import SessionStore


# --- Fake adapter that records calls ---


class RecordingAdapter(AdapterType):
    """Adapter that records all send_message calls for assertion."""

    name = "fake"

    def __init__(self):
        self.calls: list[dict] = []

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, on_raw_event=None,
                     cwd=None, resume=False):
        self.calls.append({
            "instance": instance.name,
            "user_message": user_message,
            "session_id": session_id,
            "resume": resume,
        })
        return RunResult(
            success=True,
            output=f"[recording] handled: {user_message[:80]}",
            session_id=session_id,
        )


# --- Helpers ---


def _setup_components(tmp_path: Path):
    """Wire up real queue, stores, services, and consumer with a recording adapter."""
    inst_dir = tmp_path / "instances"
    inst_dir.mkdir()
    (inst_dir / "executor.yaml").write_text(
        "name: executor\nadapter_type: fake\nconfig:\n  model: haiku\n"
    )

    routines_dir = tmp_path / "routines"
    routines_dir.mkdir()
    (routines_dir / "executor.yaml").write_text(
        "name: executor\nadapter_instance: executor\n"
        "listen: [tasks]\npublish: [completions, input_needed]\n"
    )

    queue = SQLiteQueue()
    routine_reg = RoutineRegistry(routines_dir)
    instance_reg = AdapterInstanceRegistry(inst_dir)
    session_store = SessionStore()
    request_store = RequestStore()
    request_service = RequestService(store=request_store, queue=queue)

    adapter = RecordingAdapter()
    runner = RoutineRunner(
        adapter_types={"fake": adapter},
        instance_registry=instance_reg,
        session_store=session_store,
    )

    consumer = ConsumerLoop(
        queue=queue,
        routine_registry=routine_reg,
        routine_runner=runner,
        request_service=request_service,
        session_store=session_store,
    )

    return queue, session_store, request_service, runner, consumer, adapter, routine_reg


def _auth_headers(routine: str, session: str = "test-session") -> dict:
    token = create_session_token(routine, session)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Flow 1: Request → Answer → Resume
# =============================================================================


class TestRequestAnswerResume:
    """The critical path: session creates request → user answers → session resumes."""

    def test_full_resume_flow(self, tmp_path: Path):
        """
        1. Executor session runs and creates a blocking request
        2. User answers the request (via service, simulating interlocutor)
        3. Consumer picks up the resume message
        4. Adapter is called with resume=True and the correct session_id
        """
        queue, session_store, request_service, runner, consumer, adapter, _ = (
            _setup_components(tmp_path)
        )

        # --- Step 1: Simulate an executor session that ran and completed ---
        # Create a session as if the executor ran and then ended (COMPLETED)
        original_session_id = "sess-executor-001"
        session = Session.create(
            origin=SessionOrigin.SYSTEM,
            routine_name="executor",
            adapter_instance_name="executor",
            metadata={"trigger_channel": "tasks"},
        )
        session.id = original_session_id
        session.status = SessionStatus.COMPLETED
        session_store.create_session(session)

        # --- Step 2: The executor created a blocking request before exiting ---
        request = request_service.create_request(
            session_id=original_session_id,
            type=RequestType.PERMISSION,
            summary="Merge PR #17",
            detail="Eval passed (100%), 3 files changed.",
            options=["approve", "reject"],
            created_by="executor",
        )
        assert request.status == RequestStatus.PENDING

        # Consume the input_needed message (clear it from the queue)
        queue.consume(["input_needed"], limit=10)

        # --- Step 3: User answers the request (interlocutor calls answer_request) ---
        answered = request_service.answer_request(request.id, "approve")
        assert answered.status == RequestStatus.ANSWERED
        assert answered.answer == "approve"

        # A resume message should now be in the queue
        assert queue.pending_count(["resume"]) == 1

        # --- Step 4: Consumer tick picks up resume message ---
        results = consumer.tick()

        # The adapter should have been called exactly once
        assert len(adapter.calls) == 1
        call = adapter.calls[0]

        # Verify it targeted the correct session
        assert call["session_id"] == original_session_id

        # Verify the user's answer is in the message
        assert "approve" in call["user_message"]
        assert "Merge PR #17" in call["user_message"]

        # Verify it was a resume (not a fresh session)
        assert call["resume"] is True

        # Verify the consumer result was successful
        assert len(results) == 1
        assert results[0].success is True

        # Queue should be drained (resume consumed)
        assert queue.pending_count(["resume"]) == 0

    def test_resume_with_nonexistent_request_fails_gracefully(self, tmp_path: Path):
        """Resume message with a bad request ID should fail without crashing."""
        queue, _, request_service, _, consumer, adapter, _ = (
            _setup_components(tmp_path)
        )

        # Publish a resume message with a fake request ID
        queue.publish(Message.create(
            channel="resume",
            payload={"user_response": "nonexistent-request-id"},
            source="system",
        ))

        results = consumer.tick()
        assert len(results) == 1
        assert results[0].success is False
        assert "not found" in results[0].error

        # Adapter should NOT have been called
        assert len(adapter.calls) == 0

    def test_resume_with_unanswered_request_fails_gracefully(self, tmp_path: Path):
        """Resume message for a still-pending request should fail."""
        queue, session_store, request_service, _, consumer, adapter, _ = (
            _setup_components(tmp_path)
        )

        # Create a session and request (but don't answer it)
        session = Session.create(
            origin=SessionOrigin.SYSTEM,
            routine_name="executor",
            adapter_instance_name="executor",
        )
        session.status = SessionStatus.COMPLETED
        session_store.create_session(session)

        request = request_service.create_request(
            session_id=session.id,
            type=RequestType.PERMISSION,
            summary="test",
            created_by="executor",
        )
        queue.consume(["input_needed"], limit=10)

        # Manually publish a resume message (bypassing the answer flow)
        queue.publish(Message.create(
            channel="resume",
            payload={"user_response": request.id},
            source="system",
        ))

        results = consumer.tick()
        assert len(results) == 1
        assert results[0].success is False
        assert "not answered" in results[0].error
        assert len(adapter.calls) == 0


# =============================================================================
# Flow 2: assigned_to filtering via API
# =============================================================================


class TestAssignedToAPI:
    """Work items with assigned_to='user' are queryable via the API."""

    @pytest.fixture()
    def server(self, tmp_path: Path) -> CambiumServer:
        import cambium.server.app as app_module
        import cambium.server.work_items as wi_module
        import cambium.server.requests as req_module

        user_dir = tmp_path / "user"
        skills_dir = user_dir / "adapters" / "claude-code" / "skills" / "basic"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\nname: basic\n---\n# Basic\n")

        instances_dir = user_dir / "adapters" / "claude-code" / "instances"
        instances_dir.mkdir(parents=True)
        (instances_dir / "handler.yaml").write_text(
            "name: handler\nadapter_type: claude-code\n"
            "config:\n  model: haiku\n  skills: [basic]\n"
        )

        routines_dir = user_dir / "routines"
        routines_dir.mkdir(parents=True)
        (routines_dir / "handler.yaml").write_text(
            "name: handler\nadapter_instance: handler\n"
            "listen: [tasks]\npublish: [completions]\n"
        )

        srv = build_server(db_path=":memory:", user_dir=user_dir, live=False)
        app_module._server = srv
        yield srv
        app_module._server = None
        wi_module._service = None
        req_module._service = None

    @pytest.fixture()
    def client(self, server: CambiumServer) -> TestClient:
        return TestClient(app)

    def test_create_and_filter_user_assigned_items(self, client: TestClient):
        """Create items with and without assigned_to, verify filtering works."""
        # Create a system task (no assigned_to)
        resp = client.post("/work-items", json={
            "title": "System research task",
        })
        assert resp.status_code == 201
        system_item = resp.json()
        assert system_item["assigned_to"] is None

        # Create a user-assigned task
        resp = client.post("/work-items", json={
            "title": "Run setup_oauth.py (requires your credentials)",
            "assigned_to": "user",
        })
        assert resp.status_code == 201
        user_item = resp.json()
        assert user_item["assigned_to"] == "user"

        # Filter by assigned_to=user — should return only the user task
        resp = client.get("/work-items?assigned_to=user")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == user_item["id"]
        assert data["items"][0]["assigned_to"] == "user"

        # Unfiltered — should return both
        resp = client.get("/work-items")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_assigned_to_in_decompose(self, client: TestClient):
        """Children can have assigned_to set via decompose."""
        # Create parent
        resp = client.post("/work-items", json={"title": "Parent task"})
        parent_id = resp.json()["id"]

        # Decompose with one user-assigned child
        resp = client.post(f"/work-items/{parent_id}/decompose", json={
            "children": [
                {"title": "Research phase"},
                {"title": "Run script (user)", "assigned_to": "user", "depends_on": ["$0"]},
                {"title": "Integration", "depends_on": ["$1"]},
            ]
        })
        assert resp.status_code == 200
        children = resp.json()["children"]
        assert children[0]["assigned_to"] is None
        assert children[1]["assigned_to"] == "user"
        assert children[2]["assigned_to"] is None


# =============================================================================
# Flow 3: Preference request expiry
# =============================================================================


class TestExpiryIntegration:
    """Consumer-level expiry sweep for preference requests."""

    def test_expired_preference_gets_default_applied(self, tmp_path: Path):
        """A preference request past its timeout gets expired with default applied."""
        queue, _, request_service, _, consumer, _, _ = _setup_components(tmp_path)

        # Create a preference request with a tiny timeout
        request = request_service.create_request(
            session_id="sess-1",
            type=RequestType.PREFERENCE,
            summary="Research depth?",
            detail="Survey or deep-dive?",
            options=["survey", "deep-dive"],
            default="survey",
            timeout_hours=0.0001,  # ~0.36 seconds
            created_by="planner",
        )
        queue.consume(["input_needed"], limit=10)

        # Wait just enough for the timeout to elapse
        time.sleep(0.5)

        # Force the sweep to run (reset throttle)
        consumer._last_expiry_sweep = 0

        # Tick triggers the sweep
        consumer.tick()

        # Verify the request was expired with default
        expired = request_service.get_request(request.id)
        assert expired.status == RequestStatus.EXPIRED
        assert expired.answer == "survey"  # default was applied

    def test_permission_request_never_expires(self, tmp_path: Path):
        """Permission requests should never be expired, even with timeout_hours set."""
        queue, _, request_service, _, consumer, _, _ = _setup_components(tmp_path)

        # Create a permission request — even if someone accidentally sets timeout_hours
        request = request_service.create_request(
            session_id="sess-1",
            type=RequestType.PERMISSION,
            summary="Merge PR?",
            timeout_hours=0.0001,
            created_by="executor",
        )
        queue.consume(["input_needed"], limit=10)

        time.sleep(0.5)
        consumer._last_expiry_sweep = 0
        consumer.tick()

        # Should still be pending — PERMISSION requests don't expire
        still_pending = request_service.get_request(request.id)
        assert still_pending.status == RequestStatus.PENDING


# =============================================================================
# Flow 4: Request API auth enforcement
# =============================================================================


class TestRequestAPIAuth:
    """Only the interlocutor can answer requests — enforced by the API."""

    @pytest.fixture()
    def server(self, tmp_path: Path) -> CambiumServer:
        import cambium.server.app as app_module
        import cambium.server.work_items as wi_module
        import cambium.server.requests as req_module

        user_dir = tmp_path / "user"
        skills_dir = user_dir / "adapters" / "claude-code" / "skills" / "basic"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\nname: basic\n---\n# Basic\n")

        instances_dir = user_dir / "adapters" / "claude-code" / "instances"
        instances_dir.mkdir(parents=True)
        (instances_dir / "handler.yaml").write_text(
            "name: handler\nadapter_type: claude-code\n"
            "config:\n  model: haiku\n  skills: [basic]\n"
        )
        (instances_dir / "interlocutor.yaml").write_text(
            "name: interlocutor\nadapter_type: claude-code\n"
            "config:\n  model: haiku\n  skills: [basic]\n"
        )

        routines_dir = user_dir / "routines"
        routines_dir.mkdir(parents=True)
        (routines_dir / "executor.yaml").write_text(
            "name: executor\nadapter_instance: handler\n"
            "listen: [tasks]\npublish: [completions, input_needed]\n"
        )
        (routines_dir / "interlocutor.yaml").write_text(
            "name: interlocutor\nadapter_instance: interlocutor\n"
            "listen: []\npublish: [plans, tasks, external_events, input_needed]\n"
        )

        srv = build_server(db_path=":memory:", user_dir=user_dir, live=False)
        app_module._server = srv
        yield srv
        app_module._server = None
        wi_module._service = None
        req_module._service = None

    @pytest.fixture()
    def client(self, server: CambiumServer) -> TestClient:
        return TestClient(app)

    def test_executor_cannot_answer_requests(self, client: TestClient):
        """An executor trying to answer a request gets 403."""
        # Create a request as executor
        executor_headers = _auth_headers("executor", "sess-exec")
        resp = client.post("/requests", json={
            "type": "permission",
            "summary": "Merge PR?",
            "detail": "Details here",
        }, headers=executor_headers)
        assert resp.status_code == 201
        request_id = resp.json()["id"]

        # Try to answer as executor — should be forbidden
        resp = client.post(f"/requests/{request_id}/answer", json={
            "answer": "approve",
        }, headers=executor_headers)
        assert resp.status_code == 403
        assert "interlocutor" in resp.json()["detail"]

    def test_interlocutor_can_answer_requests(self, client: TestClient):
        """The interlocutor can answer requests successfully."""
        # Create a request as executor
        executor_headers = _auth_headers("executor", "sess-exec")
        resp = client.post("/requests", json={
            "type": "permission",
            "summary": "Merge PR?",
        }, headers=executor_headers)
        assert resp.status_code == 201
        request_id = resp.json()["id"]

        # Answer as interlocutor
        interlocutor_headers = _auth_headers("interlocutor", "sess-interlocutor")
        resp = client.post(f"/requests/{request_id}/answer", json={
            "answer": "approve",
        }, headers=interlocutor_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "answered"
        assert data["answer"] == "approve"
