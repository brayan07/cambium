"""Tests for the Cambium API server."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.server.app import CambiumServer, app, build_server, _server
from cambium.server.auth import create_session_token


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    import cambium.server.app as app_module

    user_dir = tmp_path / "user"

    # Skill library
    skills_dir = user_dir / "adapters" / "claude-code" / "skills"
    skills_dir.mkdir(parents=True)
    basic = skills_dir / "basic"
    basic.mkdir()
    (basic / "SKILL.md").write_text("---\nname: basic\n---\n# Basic\n")

    # Adapter instances
    instances_dir = user_dir / "adapters" / "claude-code" / "instances"
    instances_dir.mkdir(parents=True)
    (instances_dir / "handler.yaml").write_text(
        "name: handler\nadapter_type: claude-code\n"
        "config:\n  model: haiku\n  skills: [basic]\n"
    )

    # Routines
    routines_dir = user_dir / "routines"
    routines_dir.mkdir(parents=True)
    (routines_dir / "handler.yaml").write_text(
        "name: handler\nadapter_instance: handler\n"
        "listen: [tasks, goals]\npublish: [results]\n"
    )

    srv = build_server(
        db_path=":memory:",
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
        assert "pending_messages" in data


class TestChannelEndpoints:
    def test_send_to_channel(self, client: TestClient):
        resp = client.post("/channels/tasks/send", json={"payload": {"task": "test"}})
        assert resp.status_code == 201
        data = resp.json()
        assert data["channel"] == "tasks"
        assert data["status"] == "pending"
        assert len(data["id"]) == 36

    def test_send_appears_in_queue(self, client: TestClient):
        client.post("/channels/tasks/send", json={"payload": {}})
        resp = client.get("/queue/status")
        assert resp.json()["pending"] == 1

    def test_publish_with_valid_token(self, client: TestClient):
        token = create_session_token("handler", "sess-1")
        resp = client.post(
            "/channels/results/publish",
            json={"payload": {"result": "done"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["channel"] == "results"

    def test_publish_rejected_for_unauthorized_channel(self, client: TestClient):
        token = create_session_token("handler", "sess-1")
        resp = client.post(
            "/channels/forbidden/publish",
            json={"payload": {}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_publish_rejected_without_token(self, client: TestClient):
        resp = client.post(
            "/channels/results/publish",
            json={"payload": {}},
        )
        assert resp.status_code == 401

    def test_publish_rejected_with_invalid_token(self, client: TestClient):
        resp = client.post(
            "/channels/results/publish",
            json={"payload": {}},
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401


class TestPermissionsEndpoint:
    def test_get_permissions(self, client: TestClient):
        token = create_session_token("handler", "sess-1")
        resp = client.get(
            "/channels/permissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["routine"] == "handler"
        assert "tasks" in data["listen"]
        assert "results" in data["publish"]

    def test_permissions_rejected_without_token(self, client: TestClient):
        resp = client.get("/channels/permissions")
        assert resp.status_code == 401


class TestQueueStatus:
    def test_queue_status(self, client: TestClient):
        resp = client.get("/queue/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 0
        assert "tasks" in data["subscribed_channels"]


class TestConsumerIntegration:
    def test_consumer_processes_message(self, client: TestClient, server: CambiumServer):
        client.post("/channels/tasks/send", json={"payload": {"msg": "hello"}})
        assert server.queue.pending_count() == 1

        results = server.consumer.tick()
        assert len(results) == 1
        assert results[0].success is True
        assert server.queue.pending_count() == 0
