"""End-to-end integration test for the work item planning pipeline.

Exercises the full lifecycle through the API:
coordinator creates → planner decomposes → executor claims/completes →
reviewer accepts → rollup cascades → event log
"""

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
    (routines_dir / "executor.yaml").write_text(
        "name: executor\nadapter_instance: handler\n"
        "listen: [tasks]\npublish: [completions]\n"
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


def _auth_headers(routine: str, session: str) -> dict:
    token = create_session_token(routine, session)
    return {"Authorization": f"Bearer {token}"}


class TestFullWorkItemLifecycle:
    """Coordinator → Planner → Executor → Reviewer → Rollup → Event Log."""

    def test_create_decompose_claim_complete_review_rollup(self, client: TestClient):
        # === Coordinator creates a work item ===
        resp = client.post("/work-items", json={
            "title": "Research Python testing",
            "description": "Compare pytest, unittest, and nose2",
            "priority": 5,
        })
        assert resp.status_code == 201
        root = resp.json()
        assert root["status"] == "pending"

        # === Planner decomposes into ordered children ===
        resp = client.post(f"/work-items/{root['id']}/decompose", json={
            "children": [
                {"title": "Research pytest", "priority": 3},
                {"title": "Research unittest", "priority": 2},
                {"title": "Write comparison", "priority": 1, "depends_on": ["$0", "$1"]},
            ]
        })
        assert resp.status_code == 200
        decompose_data = resp.json()
        children = decompose_data["children"]
        assert len(children) == 3

        # First two should be ready (no deps), third should be pending
        assert children[0]["status"] == "ready"
        assert children[1]["status"] == "ready"
        assert children[2]["status"] == "pending"

        # Third child's depends_on should reference first two by real IDs
        assert children[0]["id"] in children[2]["depends_on"]
        assert children[1]["id"] in children[2]["depends_on"]

        # === Executor 1 claims and completes "Research pytest" ===
        headers_e1 = _auth_headers("executor", "sess-e1")
        resp = client.post(f"/work-items/{children[0]['id']}/claim", headers=headers_e1)
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        resp = client.post(
            f"/work-items/{children[0]['id']}/complete",
            json={"result": "pytest: fast, fixture-based, plugins"},
            headers=headers_e1,
        )
        assert resp.status_code == 200

        # Third child should still be pending (not reviewed yet)
        resp = client.get(f"/work-items/{children[2]['id']}")
        assert resp.json()["status"] == "pending"

        # === Reviewer accepts first child ===
        headers_rev = _auth_headers("reviewer", "sess-rev")
        resp = client.post(
            f"/work-items/{children[0]['id']}/review",
            json={"verdict": "accepted"},
            headers=headers_rev,
        )
        assert resp.status_code == 200
        assert resp.json()["reviewed_by"] == "reviewer"

        # Third child still pending — unittest not done yet
        resp = client.get(f"/work-items/{children[2]['id']}")
        assert resp.json()["status"] == "pending"

        # Root should not be completed yet
        resp = client.get(f"/work-items/{root['id']}")
        assert resp.json()["status"] != "completed"

        # === Executor 2 claims and completes "Research unittest" ===
        headers_e2 = _auth_headers("executor", "sess-e2")
        resp = client.post(f"/work-items/{children[1]['id']}/claim", headers=headers_e2)
        assert resp.status_code == 200

        resp = client.post(
            f"/work-items/{children[1]['id']}/complete",
            json={"result": "unittest: stdlib, class-based, verbose"},
            headers=headers_e2,
        )
        assert resp.status_code == 200

        # === Reviewer accepts second child ===
        resp = client.post(
            f"/work-items/{children[1]['id']}/review",
            json={"verdict": "accepted"},
            headers=headers_rev,
        )
        assert resp.status_code == 200

        # Third child should now be ready (both deps completed AND reviewed)
        resp = client.get(f"/work-items/{children[2]['id']}")
        assert resp.json()["status"] == "ready"

        # === Executor 3 claims and completes "Write comparison" ===
        headers_e3 = _auth_headers("executor", "sess-e3")
        resp = client.post(f"/work-items/{children[2]['id']}/claim", headers=headers_e3)
        assert resp.status_code == 200

        resp = client.post(
            f"/work-items/{children[2]['id']}/complete",
            json={"result": "Comparison written: recommend pytest for this use case"},
            headers=headers_e3,
        )
        assert resp.status_code == 200

        # Root should NOT be completed yet — last child not reviewed
        resp = client.get(f"/work-items/{root['id']}")
        assert resp.json()["status"] != "completed"

        # === Reviewer accepts third child — root should auto-complete ===
        resp = client.post(
            f"/work-items/{children[2]['id']}/review",
            json={"verdict": "accepted"},
            headers=headers_rev,
        )
        assert resp.status_code == 200

        resp = client.get(f"/work-items/{root['id']}")
        root_final = resp.json()
        assert root_final["status"] == "completed"
        assert root_final["reviewed_by"] == "auto_rollup"
        assert "pytest" in root_final["result"]
        assert "unittest" in root_final["result"]
        assert "Comparison" in root_final["result"]

        # === Verify the full tree ===
        resp = client.get(f"/work-items/{root['id']}/tree")
        assert resp.status_code == 200
        tree = resp.json()
        assert len(tree) == 3
        assert all(item["status"] == "completed" for item in tree)
        assert all(item["reviewed_by"] is not None for item in tree)

        # === Verify event log ===
        resp = client.get(f"/work-items/{root['id']}/events")
        root_events = resp.json()
        event_types = [e["event_type"] for e in root_events]
        assert "created" in event_types
        assert "children_created" in event_types
        assert "status_forced" in event_types  # auto-rollup
        # Regression: auto-rollup must label reason as "auto_rollup", not "review_rejection"
        forced_events = [e for e in root_events if e["event_type"] == "status_forced"]
        assert any(e["data"]["reason"] == "auto_rollup" for e in forced_events)
        assert "reviewed" in event_types  # auto-rollup review

    def test_fail_retry_cycle(self, client: TestClient):
        """Work item fails, retries, then succeeds."""
        resp = client.post("/work-items", json={"title": "Flaky task"})
        root = resp.json()

        resp = client.post(f"/work-items/{root['id']}/decompose", json={
            "children": [{"title": "Might fail", "max_attempts": 3}]
        })
        child_id = resp.json()["children"][0]["id"]

        headers = _auth_headers("executor", "sess-1")
        headers_rev = _auth_headers("reviewer", "sess-rev")

        # First attempt: claim and fail
        client.post(f"/work-items/{child_id}/claim", headers=headers)
        resp = client.post(
            f"/work-items/{child_id}/fail",
            json={"error": "Network timeout"},
            headers=headers,
        )
        assert resp.json()["status"] == "ready"  # back to ready for retry

        # Second attempt: claim and succeed
        client.post(f"/work-items/{child_id}/claim", headers=headers)
        resp = client.post(
            f"/work-items/{child_id}/complete",
            json={"result": "Succeeded on retry"},
            headers=headers,
        )
        assert resp.json()["status"] == "completed"

        # Review to trigger rollup
        client.post(
            f"/work-items/{child_id}/review",
            json={"verdict": "accepted"},
            headers=headers_rev,
        )

        # Root should be auto-completed
        resp = client.get(f"/work-items/{root['id']}")
        assert resp.json()["status"] == "completed"

        # Check attempt count
        resp = client.get(f"/work-items/{child_id}")
        assert resp.json()["attempt_count"] == 2

    def test_block_unblock_cycle(self, client: TestClient):
        """Executor blocks on external dependency, gets unblocked, completes."""
        resp = client.post("/work-items", json={"title": "Needs API key"})
        root = resp.json()

        resp = client.post(f"/work-items/{root['id']}/decompose", json={
            "children": [{"title": "Call external API"}]
        })
        child_id = resp.json()["children"][0]["id"]

        headers = _auth_headers("executor", "sess-1")
        headers_rev = _auth_headers("reviewer", "sess-rev")

        # Claim and block
        client.post(f"/work-items/{child_id}/claim", headers=headers)
        resp = client.post(
            f"/work-items/{child_id}/block",
            json={"reason": "Waiting for API key from user"},
            headers=headers,
        )
        assert resp.json()["status"] == "blocked"

        # Unblock and complete
        client.post(f"/work-items/{child_id}/unblock", headers=headers)
        resp = client.get(f"/work-items/{child_id}")
        assert resp.json()["status"] == "ready"

        # Re-claim and complete
        client.post(f"/work-items/{child_id}/claim", headers=headers)
        client.post(
            f"/work-items/{child_id}/complete",
            json={"result": "API call succeeded"},
            headers=headers,
        )

        # Review to trigger rollup
        client.post(
            f"/work-items/{child_id}/review",
            json={"verdict": "accepted"},
            headers=headers_rev,
        )

        resp = client.get(f"/work-items/{root['id']}")
        assert resp.json()["status"] == "completed"

    def test_any_completion_mode(self, client: TestClient):
        """Parent with completion_mode=any completes on first reviewed child."""
        resp = client.post("/work-items", json={
            "title": "Try multiple approaches",
            "completion_mode": "any",
        })
        root = resp.json()

        resp = client.post(f"/work-items/{root['id']}/decompose", json={
            "children": [
                {"title": "Approach A"},
                {"title": "Approach B"},
            ]
        })
        children = resp.json()["children"]

        headers = _auth_headers("executor", "sess-1")
        headers_rev = _auth_headers("reviewer", "sess-rev")

        client.post(f"/work-items/{children[0]['id']}/claim", headers=headers)
        client.post(
            f"/work-items/{children[0]['id']}/complete",
            json={"result": "Approach A worked"},
            headers=headers,
        )

        # Root should NOT be completed yet — not reviewed
        resp = client.get(f"/work-items/{root['id']}")
        assert resp.json()["status"] != "completed"

        # Review triggers rollup
        client.post(
            f"/work-items/{children[0]['id']}/review",
            json={"verdict": "accepted"},
            headers=headers_rev,
        )

        # Now root should be completed
        resp = client.get(f"/work-items/{root['id']}")
        assert resp.json()["status"] == "completed"

        resp = client.get(f"/work-items/{children[1]['id']}")
        assert resp.json()["status"] == "ready"  # B untouched
