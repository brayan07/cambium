"""Tests for the work item API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.server.app import CambiumServer, app, build_server


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    import cambium.server.app as app_module
    import cambium.server.work_items as wi_module

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
        "listen: [tasks, events]\npublish: [results]\n"
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
    wi_module._service = None


@pytest.fixture()
def client(server: CambiumServer) -> TestClient:
    return TestClient(app)


class TestCreateWorkItem:
    def test_create(self, client: TestClient):
        resp = client.post("/work-items", json={"title": "Build feature"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Build feature"
        assert data["status"] == "pending"
        assert len(data["id"]) == 36

    def test_create_with_all_fields(self, client: TestClient):
        resp = client.post("/work-items", json={
            "title": "Complex task",
            "description": "Do the thing",
            "priority": 5,
            "completion_mode": "any",
            "rollup_mode": "synthesize",
            "context": {"key": "value"},
            "max_attempts": 5,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["priority"] == 5
        assert data["completion_mode"] == "any"
        assert data["rollup_mode"] == "synthesize"


class TestGetWorkItem:
    def test_get(self, client: TestClient):
        create_resp = client.post("/work-items", json={"title": "Test"})
        item_id = create_resp.json()["id"]

        resp = client.get(f"/work-items/{item_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == item_id

    def test_get_missing(self, client: TestClient):
        resp = client.get("/work-items/nonexistent")
        assert resp.status_code == 404


class TestDecompose:
    def test_decompose(self, client: TestClient):
        parent = client.post("/work-items", json={"title": "Parent"}).json()

        resp = client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [
                {"title": "Child 1", "priority": 2},
                {"title": "Child 2", "priority": 1},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["children"]) == 2
        assert all(c["parent_id"] == parent["id"] for c in data["children"])
        # Both should be ready (no deps)
        assert all(c["status"] == "ready" for c in data["children"])

    def test_decompose_with_dollar_refs(self, client: TestClient):
        parent = client.post("/work-items", json={"title": "Ordered"}).json()

        resp = client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [
                {"title": "First"},
                {"title": "Second", "depends_on": ["$0"]},
            ]
        })
        assert resp.status_code == 200
        children = resp.json()["children"]
        assert children[0]["status"] == "ready"
        assert children[1]["status"] == "pending"

    def test_decompose_missing_parent(self, client: TestClient):
        resp = client.post("/work-items/nonexistent/decompose", json={
            "children": [{"title": "Child"}]
        })
        assert resp.status_code == 404


class TestClaim:
    def test_claim_requires_auth(self, client: TestClient):
        parent = client.post("/work-items", json={"title": "P"}).json()
        client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [{"title": "Task"}]
        })
        children = client.get(f"/work-items/{parent['id']}/children").json()

        resp = client.post(f"/work-items/{children[0]['id']}/claim")
        assert resp.status_code == 401

    def test_claim_non_ready_returns_409(self, client: TestClient):
        from cambium.server.auth import create_session_token
        item = client.post("/work-items", json={"title": "Pending"}).json()
        token = create_session_token("handler", "sess-1")

        resp = client.post(
            f"/work-items/{item['id']}/claim",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409


class TestComplete:
    def test_complete_updates_status(self, client: TestClient):
        from cambium.server.auth import create_session_token
        parent = client.post("/work-items", json={"title": "P"}).json()
        decompose_resp = client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [{"title": "Task"}]
        })
        child_id = decompose_resp.json()["children"][0]["id"]

        token = create_session_token("handler", "sess-1")
        headers = {"Authorization": f"Bearer {token}"}

        # Claim
        client.post(f"/work-items/{child_id}/claim", headers=headers)

        # Complete
        resp = client.post(
            f"/work-items/{child_id}/complete",
            json={"result": "Done!"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        assert resp.json()["result"] == "Done!"


class TestFail:
    def test_fail_retries(self, client: TestClient):
        from cambium.server.auth import create_session_token
        parent = client.post("/work-items", json={"title": "P"}).json()
        decompose_resp = client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [{"title": "Fragile", "max_attempts": 3}]
        })
        child_id = decompose_resp.json()["children"][0]["id"]

        token = create_session_token("handler", "sess-1")
        headers = {"Authorization": f"Bearer {token}"}
        client.post(f"/work-items/{child_id}/claim", headers=headers)

        resp = client.post(
            f"/work-items/{child_id}/fail",
            json={"error": "oops"},
            headers=headers,
        )
        assert resp.status_code == 200
        # Should be back to ready for retry
        assert resp.json()["status"] == "ready"


class TestBlockUnblock:
    def test_block_and_unblock(self, client: TestClient):
        from cambium.server.auth import create_session_token
        parent = client.post("/work-items", json={"title": "P"}).json()
        decompose_resp = client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [{"title": "Task"}]
        })
        child_id = decompose_resp.json()["children"][0]["id"]

        token = create_session_token("handler", "sess-1")
        headers = {"Authorization": f"Bearer {token}"}
        client.post(f"/work-items/{child_id}/claim", headers=headers)

        # Block
        resp = client.post(
            f"/work-items/{child_id}/block",
            json={"reason": "Waiting"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "blocked"

        # Unblock
        resp = client.post(f"/work-items/{child_id}/unblock", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"


class TestContext:
    def test_patch_context(self, client: TestClient):
        item = client.post("/work-items", json={"title": "Task"}).json()

        resp = client.patch(
            f"/work-items/{item['id']}/context",
            json={"key": "value"},
        )
        assert resp.status_code == 200
        assert resp.json()["context"]["key"] == "value"


class TestChildren:
    def test_get_children(self, client: TestClient):
        parent = client.post("/work-items", json={"title": "P"}).json()
        client.post(f"/work-items/{parent['id']}/decompose", json={
            "children": [{"title": "A"}, {"title": "B"}]
        })

        resp = client.get(f"/work-items/{parent['id']}/children")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestTree:
    def test_get_tree(self, client: TestClient):
        root = client.post("/work-items", json={"title": "Root"}).json()
        decompose_resp = client.post(f"/work-items/{root['id']}/decompose", json={
            "children": [{"title": "Mid"}]
        })
        mid_id = decompose_resp.json()["children"][0]["id"]
        client.post(f"/work-items/{mid_id}/decompose", json={
            "children": [{"title": "Leaf"}]
        })

        resp = client.get(f"/work-items/{root['id']}/tree")
        assert resp.status_code == 200
        assert len(resp.json()) == 2  # Mid + Leaf


class TestListItems:
    def test_list_all(self, client: TestClient):
        client.post("/work-items", json={"title": "A"})
        client.post("/work-items", json={"title": "B"})

        resp = client.get("/work-items")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_list_by_status(self, client: TestClient):
        client.post("/work-items", json={"title": "Pending"})

        resp = client.get("/work-items?status=pending")
        assert resp.status_code == 200
        assert all(i["status"] == "pending" for i in resp.json())


class TestEvents:
    def test_get_item_events(self, client: TestClient):
        item = client.post("/work-items", json={"title": "Task"}).json()

        resp = client.get(f"/work-items/{item['id']}/events")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        assert resp.json()[0]["event_type"] == "created"

    def test_get_all_events(self, client: TestClient):
        client.post("/work-items", json={"title": "A"})
        client.post("/work-items", json={"title": "B"})

        resp = client.get("/work-items/events/all")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2
