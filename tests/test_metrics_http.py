"""HTTP endpoint tests for the metrics API — TestClient level."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.server.app import CambiumServer, app, build_server
from cambium.server.auth import create_session_token


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    import cambium.server.app as app_module

    user_dir = tmp_path / "user"

    # Minimal skill
    skills_dir = user_dir / "adapters" / "claude-code" / "skills"
    skills_dir.mkdir(parents=True)
    basic = skills_dir / "basic"
    basic.mkdir()
    (basic / "SKILL.md").write_text("---\nname: basic\n---\n# Basic\n")

    # Minimal instance
    instances_dir = user_dir / "adapters" / "claude-code" / "instances"
    instances_dir.mkdir(parents=True)
    (instances_dir / "handler.yaml").write_text(
        "name: handler\nadapter_type: claude-code\n"
        "config:\n  model: haiku\n  skills: [basic]\n"
    )

    # Minimal routine
    routines_dir = user_dir / "routines"
    routines_dir.mkdir(parents=True)
    (routines_dir / "handler.yaml").write_text(
        "name: handler\nadapter_instance: handler\n"
        "listen: [tasks]\npublish: [results]\n"
    )

    # Metrics config
    (user_dir / "metrics.yaml").write_text(
        "metrics:\n"
        "  - name: test_det\n"
        "    type: deterministic\n"
        "    description: Test deterministic metric\n"
        "    unit: ratio\n"
        "    tags: [health]\n"
        "    schedule: '0 */6 * * *'\n"
        "    script_path: test.sh\n"
        "  - name: test_intel\n"
        "    type: intelligent\n"
        "    description: Test intelligent metric\n"
        "    unit: score_0_1\n"
        "    tags: [alignment]\n"
        "    schedule: '0 6 * * *'\n"
        "    instance: metric-analyst-heavy\n"
    )

    srv = build_server(db_path=":memory:", user_dir=user_dir, live=False)
    app_module._server = srv
    yield srv
    app_module._server = None


@pytest.fixture()
def client(server: CambiumServer) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth_header() -> dict[str, str]:
    token = create_session_token("test-routine", "test-session")
    return {"Authorization": f"Bearer {token}"}


# ── GET endpoints — no auth required ─────────────────────────────────


class TestGetEndpointsNoAuth:
    """GET endpoints should work without an Authorization header."""

    def test_list_metrics(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0  # seed metrics from defaults

    def test_list_metrics_filter_by_type(self, client: TestClient) -> None:
        resp = client.get("/metrics", params={"type": "deterministic"})
        assert resp.status_code == 200
        for m in resp.json():
            assert m["type"] == "deterministic"

    def test_list_metrics_filter_by_tag(self, client: TestClient) -> None:
        resp = client.get("/metrics", params={"tag": "alignment"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "test_intel"

    def test_get_single_metric(self, client: TestClient) -> None:
        resp = client.get("/metrics/test_det")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test_det"
        assert data["type"] == "deterministic"

    def test_get_metric_not_found(self, client: TestClient) -> None:
        resp = client.get("/metrics/nonexistent")
        assert resp.status_code == 404

    def test_list_readings_empty(self, client: TestClient) -> None:
        resp = client.get("/metrics/test_det/readings")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_readings_not_found_metric(self, client: TestClient) -> None:
        resp = client.get("/metrics/nonexistent/readings")
        assert resp.status_code == 404

    def test_get_summary_empty(self, client: TestClient) -> None:
        resp = client.get("/metrics/test_det/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["latest_value"] is None


# ── POST endpoints — auth required ───────────────────────────────────


class TestPostEndpointsAuth:
    """POST /metrics/{name}/readings requires authentication."""

    def test_post_reading_no_auth_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/metrics/test_det/readings",
            json={"value": 0.8, "detail": "test"},
        )
        assert resp.status_code == 401

    def test_post_reading_with_auth(self, client: TestClient, auth_header) -> None:
        resp = client.post(
            "/metrics/test_det/readings",
            json={"value": 0.8, "detail": "test reading", "source": "test"},
            headers=auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["value"] == 0.8
        assert data["detail"] == "test reading"
        assert data["metric_name"] == "test_det"

    def test_post_reading_nonexistent_metric(self, client: TestClient, auth_header) -> None:
        resp = client.post(
            "/metrics/nonexistent/readings",
            json={"value": 0.5},
            headers=auth_header,
        )
        assert resp.status_code == 404

    def test_reading_visible_after_post(self, client: TestClient, auth_header) -> None:
        client.post(
            "/metrics/test_det/readings",
            json={"value": 0.75, "detail": "visible"},
            headers=auth_header,
        )
        resp = client.get("/metrics/test_det/readings")
        assert resp.status_code == 200
        readings = resp.json()
        assert len(readings) == 1
        assert readings[0]["value"] == 0.75

    def test_summary_after_post(self, client: TestClient, auth_header) -> None:
        for v in [0.6, 0.8, 1.0]:
            client.post(
                "/metrics/test_det/readings",
                json={"value": v, "source": "test"},
                headers=auth_header,
            )
        resp = client.get("/metrics/test_det/summary")
        data = resp.json()
        assert data["count"] == 3
        assert data["min"] == 0.6
        assert data["max"] == 1.0


# ── Seed endpoint — no auth ──────────────────────────────────────────


class TestSeedEndpoint:
    def test_seed_readings(self, client: TestClient) -> None:
        resp = client.post("/metrics/seed", json=[
            {"metric_name": "test_det", "value": 0.9, "detail": "seed"},
        ])
        assert resp.status_code == 201
        assert len(resp.json()) == 1

    def test_seed_nonexistent_metric(self, client: TestClient) -> None:
        resp = client.post("/metrics/seed", json=[
            {"metric_name": "nonexistent", "value": 0.5},
        ])
        assert resp.status_code == 404
