"""Tests for the session API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.server.app import CambiumServer, app, build_server


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    import cambium.server.app as app_module

    fw = tmp_path / "framework"

    # Skill library
    skills_dir = fw / "defaults" / "skills"
    skills_dir.mkdir(parents=True)
    basic = skills_dir / "basic"
    basic.mkdir()
    (basic / "SKILL.md").write_text("---\nname: basic\n---\n# Basic\n")

    # Adapter instances
    instances_dir = fw / "defaults" / "adapters" / "claude-code" / "instances"
    instances_dir.mkdir(parents=True)
    (instances_dir / "handler.yaml").write_text(
        "name: handler\nadapter_type: claude-code\n"
        "config:\n  model: haiku\n  skills: [basic]\n"
    )

    # Routines
    routines_dir = fw / "defaults" / "routines"
    routines_dir.mkdir(parents=True)
    (routines_dir / "handler.yaml").write_text(
        "name: handler\nadapter_instance: handler\n"
        "listen: [tasks, goals]\npublish: [results]\n"
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


class TestCreateSession:
    def test_create_interactive_session(self, client: TestClient):
        resp = client.post("/sessions", json={"routine_name": "handler"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "interactive"
        assert data["status"] == "created"
        assert data["routine_name"] == "handler"
        assert len(data["id"]) == 36

    def test_create_session_with_missing_routine(self, client: TestClient):
        resp = client.post("/sessions", json={"routine_name": "nonexistent"})
        assert resp.status_code == 404

    def test_create_session_with_metadata(self, client: TestClient):
        resp = client.post("/sessions", json={
            "routine_name": "handler",
            "metadata": {"transport": "slack", "channel_id": "C123"},
        })
        assert resp.status_code == 201
        assert resp.json()["metadata"]["transport"] == "slack"


class TestGetSession:
    def test_get_session(self, client: TestClient):
        create_resp = client.post("/sessions", json={"routine_name": "handler"})
        session_id = create_resp.json()["id"]

        resp = client.get(f"/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == session_id

    def test_get_missing_session(self, client: TestClient):
        resp = client.get("/sessions/nonexistent")
        assert resp.status_code == 404


class TestDeleteSession:
    def test_delete_session(self, client: TestClient):
        create_resp = client.post("/sessions", json={"routine_name": "handler"})
        session_id = create_resp.json()["id"]

        resp = client.delete(f"/sessions/{session_id}")
        assert resp.status_code == 204

        # Verify status changed
        get_resp = client.get(f"/sessions/{session_id}")
        assert get_resp.json()["status"] == "completed"

    def test_delete_missing_session(self, client: TestClient):
        resp = client.delete("/sessions/nonexistent")
        assert resp.status_code == 404


class TestGetMessages:
    def test_get_messages_empty_session(self, client: TestClient):
        create_resp = client.post("/sessions", json={"routine_name": "handler"})
        session_id = create_resp.json()["id"]

        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_messages_missing_session(self, client: TestClient):
        resp = client.get("/sessions/nonexistent/messages")
        assert resp.status_code == 404


class TestSendMessage:
    def test_send_message_streams_sse(self, client: TestClient):
        # Create session
        create_resp = client.post("/sessions", json={"routine_name": "handler"})
        session_id = create_resp.json()["id"]

        # Send message with streaming
        with client.stream(
            "POST",
            f"/sessions/{session_id}/messages",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    lines.append(line)

        # Should have at least one data chunk and [DONE]
        assert len(lines) >= 2
        assert lines[-1] == "data: [DONE]"

        # First data chunks should be OpenAI format
        import json
        first_data = json.loads(lines[0].removeprefix("data: "))
        assert first_data["object"] == "chat.completion.chunk"
        assert "choices" in first_data

    def test_send_message_to_missing_session(self, client: TestClient):
        resp = client.post(
            "/sessions/nonexistent/messages",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 404

    def test_send_message_stores_conversation(self, client: TestClient):
        # Create session
        create_resp = client.post("/sessions", json={"routine_name": "handler"})
        session_id = create_resp.json()["id"]

        # Send message (consume full stream)
        with client.stream(
            "POST",
            f"/sessions/{session_id}/messages",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        ) as resp:
            for _ in resp.iter_lines():
                pass

        # Check messages were stored
        msgs_resp = client.get(f"/sessions/{session_id}/messages")
        messages = msgs_resp.json()
        assert len(messages) >= 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_send_message_no_user_message(self, client: TestClient):
        create_resp = client.post("/sessions", json={"routine_name": "handler"})
        session_id = create_resp.json()["id"]

        resp = client.post(
            f"/sessions/{session_id}/messages",
            json={"messages": [{"role": "system", "content": "You are helpful"}]},
        )
        assert resp.status_code == 400


class TestStreamSession:
    def test_stream_missing_session(self, client: TestClient):
        resp = client.get("/sessions/nonexistent/stream")
        assert resp.status_code == 404
