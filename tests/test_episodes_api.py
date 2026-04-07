"""Tests for the episodic memory API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cambium.episode.model import Episode, EpisodeStatus
from cambium.episode.store import EpisodeStore
from cambium.server.app import CambiumServer, app, build_server
from cambium.server.auth import create_session_token


def _ts(offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


@pytest.fixture()
def server(tmp_path: Path) -> CambiumServer:
    import cambium.server.app as app_module

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
    (routines_dir / "handler.yaml").write_text(
        "name: handler\nadapter_instance: handler\n"
        "listen: [tasks]\npublish: [results]\n"
    )

    srv = build_server(db_path=":memory:", user_dir=user_dir, live=False)
    app_module._server = srv
    yield srv
    app_module._server = None
    app_module._episode_store = None


@pytest.fixture()
def client(server: CambiumServer) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def episode_store(server: CambiumServer) -> EpisodeStore:
    import cambium.server.app as app_module
    return app_module._episode_store


class TestListEpisodes:
    def test_list_with_time_range(self, client: TestClient, episode_store: EpisodeStore):
        ep = Episode.create(session_id="s1", routine="executor")
        episode_store.create_episode(ep)

        resp = client.get("/episodes", params={"since": _ts(-60), "until": _ts(60)})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "s1"

    def test_list_with_routine_filter(self, client: TestClient, episode_store: EpisodeStore):
        ep1 = Episode.create(session_id="s2", routine="executor")
        ep2 = Episode.create(session_id="s3", routine="planner")
        episode_store.create_episode(ep1)
        episode_store.create_episode(ep2)

        resp = client.get("/episodes", params={
            "since": _ts(-60), "until": _ts(60), "routine": "planner",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["routine"] == "planner"

    def test_list_requires_since_and_until(self, client: TestClient):
        resp = client.get("/episodes")
        assert resp.status_code == 422


class TestGetEpisode:
    def test_get_by_id(self, client: TestClient, episode_store: EpisodeStore):
        ep = Episode.create(session_id="s4", routine="coordinator")
        episode_store.create_episode(ep)

        resp = client.get(f"/episodes/{ep.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == ep.id

    def test_get_not_found(self, client: TestClient):
        resp = client.get("/episodes/nonexistent")
        assert resp.status_code == 404


class TestPostSummary:
    def test_post_summary(self, client: TestClient, episode_store: EpisodeStore):
        ep = Episode.create(session_id="s5", routine="handler")
        episode_store.create_episode(ep)

        token = create_session_token("handler", "s5")
        resp = client.post(
            "/episodes/summary",
            json={"summary": "Completed the task successfully."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_acknowledged"] is True
        assert data["session_summary"] == "Completed the task successfully."

    def test_post_summary_requires_auth(self, client: TestClient):
        resp = client.post("/episodes/summary", json={"summary": "test"})
        assert resp.status_code == 401

    def test_post_summary_no_episode(self, client: TestClient):
        token = create_session_token("handler", "no-such-session")
        resp = client.post(
            "/episodes/summary",
            json={"summary": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestEventEndpoints:
    def test_send_records_event(self, client: TestClient, episode_store: EpisodeStore):
        """External send to a channel should record a ChannelEvent."""
        client.post("/channels/tasks/send", json={"payload": {"task": "hello"}})

        events = episode_store.list_events(channel="tasks")
        assert len(events) == 1
        assert events[0].payload == {"task": "hello"}
        assert events[0].source_session_id is None

    def test_publish_records_event_with_session(self, client: TestClient, episode_store: EpisodeStore):
        """Authenticated publish should record event linked to the session."""
        # Create an episode for this session first
        ep = Episode.create(session_id="s6", routine="handler")
        episode_store.create_episode(ep)

        token = create_session_token("handler", "s6")
        client.post(
            "/channels/results/publish",
            json={"payload": {"result": "done"}},
            headers={"Authorization": f"Bearer {token}"},
        )

        events = episode_store.list_events(channel="results")
        assert len(events) == 1
        assert events[0].source_session_id == "s6"

        # Verify event was appended to episode's emitted_event_ids
        got_ep = episode_store.get_episode(ep.id)
        assert len(got_ep.emitted_event_ids) == 1
        assert got_ep.emitted_event_ids[0] == events[0].id

    def test_list_events_by_channel(self, client: TestClient, episode_store: EpisodeStore):
        client.post("/channels/tasks/send", json={"payload": {"a": 1}})
        client.post("/channels/tasks/send", json={"payload": {"b": 2}})

        resp = client.get("/events", params={"channel": "tasks"})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_event_by_id(self, client: TestClient, episode_store: EpisodeStore):
        client.post("/channels/tasks/send", json={"payload": {"x": 1}})
        events = episode_store.list_events(channel="tasks")
        event_id = events[0].id

        resp = client.get(f"/events/{event_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == event_id

    def test_get_event_not_found(self, client: TestClient):
        resp = client.get("/events/nonexistent")
        assert resp.status_code == 404
