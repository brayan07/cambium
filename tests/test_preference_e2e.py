"""End-to-end integration tests for preference learning through the API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.server.app import CambiumServer, app, build_server
from cambium.server.auth import create_session_token


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    import cambium.server.app as app_module
    import cambium.server.work_items as wi_module
    import cambium.server.preferences as pref_module

    user_dir = tmp_path / "user"

    skills_dir = user_dir / "adapters" / "claude-code" / "skills"
    skills_dir.mkdir(parents=True)
    basic = skills_dir / "basic"
    basic.mkdir()
    (basic / "SKILL.md").write_text("---\nname: basic\n---\n# Basic\n")

    instances_dir = user_dir / "adapters" / "claude-code" / "instances"
    instances_dir.mkdir(parents=True)
    (instances_dir / "handler.yaml").write_text(
        "name: handler\nadapter_type: claude-code\n"
        "config:\n  model: haiku\n  skills: [basic]\n"
    )

    routines_dir = user_dir / "routines"
    routines_dir.mkdir(parents=True)
    (routines_dir / "planner.yaml").write_text(
        "name: planner\nadapter_instance: handler\n"
        "listen: [plans]\npublish: [tasks]\n"
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
    pref_module._service = None


@pytest.fixture()
def client(server: CambiumServer) -> TestClient:
    return TestClient(app)


def _auth_headers(routine: str, session: str) -> dict:
    token = create_session_token(routine, session)
    return {"Authorization": f"Bearer {token}"}


class TestPreferenceDimensions:
    def test_list_dimensions(self, client: TestClient):
        resp = client.get("/preferences/dimensions")
        assert resp.status_code == 200
        dims = resp.json()
        assert len(dims) == 5
        names = {d["name"] for d in dims}
        assert "research_depth" in names

    def test_get_dimension_state(self, client: TestClient):
        resp = client.get("/preferences/dimensions/research_depth/state")
        assert resp.status_code == 200
        state = resp.json()
        assert 0.6 < state["mean"] < 0.7
        assert state["context_key"] == "global"

    def test_nonexistent_dimension(self, client: TestClient):
        resp = client.get("/preferences/dimensions/nonexistent/state")
        assert resp.status_code == 404


class TestPreferenceContext:
    def test_context_for_work_item(self, client: TestClient):
        # Create a work item
        resp = client.post("/work-items", json={
            "title": "Research AI safety orgs",
            "context": {"domain": "career", "task_type": "research"},
        })
        assert resp.status_code == 201
        item_id = resp.json()["id"]

        # Get preference context
        resp = client.get(f"/preferences/context/{item_id}")
        assert resp.status_code == 200
        ctx = resp.json()
        assert len(ctx["dimensions"]) > 0
        assert "prompt_text" in ctx
        assert "research_depth" in ctx["prompt_text"] or "quality_bar" in ctx["prompt_text"]


class TestSignalFlow:
    def test_review_creates_signals(self, client: TestClient):
        """Full flow: create → decompose → claim → complete → review → signals exist."""
        # Create parent
        resp = client.post("/work-items", json={"title": "Parent"})
        parent_id = resp.json()["id"]

        # Decompose
        resp = client.post(f"/work-items/{parent_id}/decompose", json={
            "children": [{"title": "Research task", "context": {"domain": "career", "task_type": "research"}}]
        })
        child_id = resp.json()["children"][0]["id"]

        # Claim and complete
        headers = _auth_headers("executor", "sess-1")
        client.post(f"/work-items/{child_id}/claim", headers=headers)
        client.post(f"/work-items/{child_id}/complete",
                     json={"result": "Found 3 relevant orgs"}, headers=headers)

        # Review with rejection
        headers_rev = _auth_headers("reviewer", "sess-rev")
        resp = client.post(f"/work-items/{child_id}/review",
                           json={"verdict": "rejected", "feedback": "Too shallow, need more sources"},
                           headers=headers_rev)
        assert resp.status_code == 200

        # Check signals were created
        resp = client.get("/preferences/signals", params={"source_item_id": child_id})
        assert resp.status_code == 200
        signals = resp.json()
        assert len(signals) > 0

    def test_acceptance_creates_weaker_signals(self, client: TestClient):
        resp = client.post("/work-items", json={"title": "Parent"})
        parent_id = resp.json()["id"]

        resp = client.post(f"/work-items/{parent_id}/decompose", json={
            "children": [{"title": "Simple task"}]
        })
        child_id = resp.json()["children"][0]["id"]

        headers = _auth_headers("executor", "sess-1")
        client.post(f"/work-items/{child_id}/claim", headers=headers)
        client.post(f"/work-items/{child_id}/complete",
                     json={"result": "Done"}, headers=headers)

        headers_rev = _auth_headers("reviewer", "sess-rev")
        client.post(f"/work-items/{child_id}/review",
                     json={"verdict": "accepted"}, headers=headers_rev)

        resp = client.get("/preferences/signals", params={"source_item_id": child_id})
        signals = resp.json()
        # Acceptance signals should have high observation_variance (weak)
        assert all(s["observation_variance"] >= 0.20 for s in signals)


class TestCasesAPI:
    def test_create_and_list_cases(self, client: TestClient):
        # Create a work item for provenance
        resp = client.post("/work-items", json={
            "title": "Research task",
            "context": {"domain": "career", "task_type": "research"},
        })
        item_id = resp.json()["id"]

        # Create a case
        resp = client.post("/preferences/cases", json={
            "work_item_id": item_id,
            "lesson": "Always include primary sources for career research",
            "verdict": "rejected",
            "feedback": "Too shallow",
        })
        assert resp.status_code == 201
        case = resp.json()
        assert case["signal_direction"] == -1.0

        # List cases
        resp = client.get("/preferences/cases")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestObjectivesAPI:
    def test_list_objectives(self, client: TestClient):
        resp = client.get("/preferences/objectives")
        assert resp.status_code == 200
        objs = resp.json()
        assert len(objs) == 5

    def test_record_and_get_reports(self, client: TestClient):
        resp = client.post("/preferences/objectives/mood/report",
                           json={"value": 4.0, "notes": "Good day"})
        assert resp.status_code == 201

        resp = client.get("/preferences/objectives/mood/reports")
        assert resp.status_code == 200
        reports = resp.json()
        assert len(reports) == 1
        assert reports[0]["value"] == 4.0

    def test_nonexistent_objective(self, client: TestClient):
        resp = client.post("/preferences/objectives/fake/report",
                           json={"value": 3.0})
        assert resp.status_code == 404
