"""Tests for the Cambium API server."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.server.app import CambiumServer, app, build_server, _server


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    """Build a test server with temp dirs and in-memory queue."""
    import cambium.server.app as app_module

    # Create minimal framework structure
    fw = tmp_path / "framework"
    skills_dir = fw / "defaults" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "basic.md").write_text("---\nname: basic\n---\n# Basic\n")

    routines_dir = fw / "defaults" / "routines"
    routines_dir.mkdir(parents=True)
    prompts_dir = routines_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "handler.md").write_text("You handle tasks.\n")
    (routines_dir / "handler.yaml").write_text(
        "name: handler\nprompt_path: prompts/handler.md\nskills: [basic]\n"
        "subscribe: [test_event, goal_created]\nemit: [task_queued]\n"
    )

    user_dir = tmp_path / "user"
    user_dir.mkdir()

    srv = build_server(
        db_path=":memory:",
        framework_dir=fw,
        user_dir=user_dir,
        live=False,
        poll_interval=0.1,
    )
    app_module._server = srv
    yield srv
    app_module._server = None


@pytest.fixture()
def client(server: CambiumServer) -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "pending_events" in data


class TestEventsEndpoint:
    def test_create_event(self, client: TestClient):
        resp = client.post("/events", json={
            "type": "goal_created",
            "payload": {"goal": "test"},
            "source": "test",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "goal_created"
        assert data["payload"] == {"goal": "test"}
        assert data["status"] == "pending"
        assert len(data["id"]) == 36  # UUID

    def test_create_event_minimal(self, client: TestClient):
        resp = client.post("/events", json={"type": "ping"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "ping"
        assert data["payload"] == {}
        assert data["source"] == "api"

    def test_create_event_appears_in_queue(self, client: TestClient):
        client.post("/events", json={"type": "test_event"})
        resp = client.get("/queue/status")
        assert resp.json()["pending"] == 1


class TestQueueEndpoints:
    def test_queue_status(self, client: TestClient):
        resp = client.get("/queue/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 0
        assert "test_event" in data["subscribed_event_types"]

    def test_ack_event(self, client: TestClient, server: CambiumServer):
        # Enqueue and dequeue to get an in-flight event
        resp = client.post("/events", json={"type": "test_event"})
        event_id = resp.json()["id"]

        # Dequeue it (moves to in_flight)
        events = server.queue.dequeue(["test_event"])
        assert len(events) == 1

        # Ack it
        resp = client.post(f"/queue/{event_id}/ack")
        assert resp.status_code == 200
        assert server.queue.pending_count() == 0

    def test_nack_event(self, client: TestClient, server: CambiumServer):
        resp = client.post("/events", json={"type": "test_event"})
        event_id = resp.json()["id"]

        events = server.queue.dequeue(["test_event"])
        assert len(events) == 1

        # Nack it — should go back to pending
        resp = client.post(f"/queue/{event_id}/nack")
        assert resp.status_code == 200
        assert server.queue.pending_count() == 1


class TestConsumerIntegration:
    def test_consumer_processes_event(self, client: TestClient, server: CambiumServer):
        """Enqueue an event, run one tick, verify it gets processed."""
        client.post("/events", json={
            "type": "test_event",
            "payload": {"msg": "hello"},
        })
        assert server.queue.pending_count() == 1

        # Run one consumer tick manually
        results = server.consumer.tick()
        assert len(results) == 1
        assert results[0].success is True
        assert server.queue.pending_count() == 0
