"""Tests for the episodic memory store."""

from datetime import datetime, timedelta, timezone

from cambium.episode.model import ChannelEvent, Episode, EpisodeStatus
from cambium.episode.store import EpisodeStore


def _ts(offset_minutes: int = 0) -> str:
    """ISO timestamp with optional offset from now."""
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


class TestEpisodeCreation:
    def test_create_and_get(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-1", routine="executor")
        store.create_episode(ep)

        got = store.get_episode(ep.id)
        assert got is not None
        assert got.id == ep.id
        assert got.session_id == "sess-1"
        assert got.routine == "executor"
        assert got.status == EpisodeStatus.RUNNING
        assert got.trigger_event_ids == []
        assert got.emitted_event_ids == []
        assert got.session_acknowledged is False
        assert got.session_summary is None
        assert got.summarizer_acknowledged is False
        assert got.digest_path is None

    def test_create_with_trigger_events(self):
        store = EpisodeStore()
        ep = Episode.create(
            session_id="sess-2",
            routine="planner",
            trigger_event_ids=["evt-1", "evt-2"],
        )
        store.create_episode(ep)

        got = store.get_episode(ep.id)
        assert got.trigger_event_ids == ["evt-1", "evt-2"]

    def test_get_by_session(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-3", routine="coordinator")
        store.create_episode(ep)

        got = store.get_episode_by_session("sess-3")
        assert got is not None
        assert got.id == ep.id

    def test_get_by_session_returns_none(self):
        store = EpisodeStore()
        assert store.get_episode_by_session("nonexistent") is None

    def test_get_returns_none(self):
        store = EpisodeStore()
        assert store.get_episode("nonexistent") is None


class TestEpisodeLifecycle:
    def test_complete_episode(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-4", routine="executor")
        store.create_episode(ep)

        store.complete_episode("sess-4", EpisodeStatus.COMPLETED)
        got = store.get_episode(ep.id)
        assert got.status == EpisodeStatus.COMPLETED
        assert got.ended_at is not None

    def test_complete_failed(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-5", routine="executor")
        store.create_episode(ep)

        store.complete_episode("sess-5", EpisodeStatus.FAILED)
        got = store.get_episode(ep.id)
        assert got.status == EpisodeStatus.FAILED
        assert got.ended_at is not None

    def test_complete_only_affects_running(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-6", routine="executor")
        store.create_episode(ep)
        store.complete_episode("sess-6", EpisodeStatus.COMPLETED)

        # Completing again should not change anything (already completed)
        store.complete_episode("sess-6", EpisodeStatus.FAILED)
        got = store.get_episode(ep.id)
        assert got.status == EpisodeStatus.COMPLETED

    def test_acknowledge_session(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-7", routine="executor")
        store.create_episode(ep)

        store.acknowledge_session("sess-7", "Completed task X and published results.")
        got = store.get_episode(ep.id)
        assert got.session_acknowledged is True
        assert got.session_summary == "Completed task X and published results."

    def test_acknowledge_summarizer(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-8", routine="executor")
        store.create_episode(ep)

        store.acknowledge_summarizer("sess-8", "sessions/2026-04-06/sess-8.md")
        got = store.get_episode(ep.id)
        assert got.summarizer_acknowledged is True
        assert got.digest_path == "sessions/2026-04-06/sess-8.md"


class TestEmittedEvents:
    def test_append_single(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-9", routine="executor")
        store.create_episode(ep)

        store.append_emitted_event("sess-9", "evt-10")
        got = store.get_episode(ep.id)
        assert got.emitted_event_ids == ["evt-10"]

    def test_append_multiple(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-10", routine="executor")
        store.create_episode(ep)

        store.append_emitted_event("sess-10", "evt-a")
        store.append_emitted_event("sess-10", "evt-b")
        store.append_emitted_event("sess-10", "evt-c")

        got = store.get_episode(ep.id)
        assert got.emitted_event_ids == ["evt-a", "evt-b", "evt-c"]

    def test_append_to_completed_is_noop(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="sess-11", routine="executor")
        store.create_episode(ep)
        store.complete_episode("sess-11", EpisodeStatus.COMPLETED)

        # Should silently do nothing — only appends to running episodes
        store.append_emitted_event("sess-11", "evt-late")
        got = store.get_episode(ep.id)
        assert got.emitted_event_ids == []

    def test_append_to_nonexistent_is_noop(self):
        store = EpisodeStore()
        # Should not raise
        store.append_emitted_event("nonexistent", "evt-x")


class TestEpisodeListing:
    def test_list_by_time_range(self):
        store = EpisodeStore()
        past = _ts(-60)
        recent = _ts(-5)
        future = _ts(60)

        ep1 = Episode.create(session_id="s1", routine="executor")
        ep1.started_at = past
        store.create_episode(ep1)

        ep2 = Episode.create(session_id="s2", routine="planner")
        ep2.started_at = recent
        store.create_episode(ep2)

        # Query covering both
        results = store.list_episodes(since=_ts(-120), until=future)
        assert len(results) == 2

        # Query covering only recent
        results = store.list_episodes(since=_ts(-10), until=future)
        assert len(results) == 1
        assert results[0].session_id == "s2"

    def test_list_by_routine(self):
        store = EpisodeStore()
        now = _ts()
        future = _ts(60)

        ep1 = Episode.create(session_id="s3", routine="executor")
        ep1.started_at = now
        store.create_episode(ep1)

        ep2 = Episode.create(session_id="s4", routine="planner")
        ep2.started_at = now
        store.create_episode(ep2)

        results = store.list_episodes(since=_ts(-1), until=future, routine="executor")
        assert len(results) == 1
        assert results[0].routine == "executor"

    def test_list_respects_limit(self):
        store = EpisodeStore()
        now = _ts()
        for i in range(5):
            ep = Episode.create(session_id=f"s-{i}", routine="executor")
            ep.started_at = now
            store.create_episode(ep)

        results = store.list_episodes(since=_ts(-1), until=_ts(1), limit=3)
        assert len(results) == 3

    def test_list_ordered_by_started_at_desc(self):
        store = EpisodeStore()
        ep_old = Episode.create(session_id="old", routine="executor")
        ep_old.started_at = _ts(-30)
        store.create_episode(ep_old)

        ep_new = Episode.create(session_id="new", routine="executor")
        ep_new.started_at = _ts(-5)
        store.create_episode(ep_new)

        results = store.list_episodes(since=_ts(-60), until=_ts(1))
        assert results[0].session_id == "new"
        assert results[1].session_id == "old"


class TestUnacknowledged:
    def test_unacknowledged_by_session(self):
        store = EpisodeStore()
        ep1 = Episode.create(session_id="u1", routine="executor")
        store.create_episode(ep1)
        store.complete_episode("u1", EpisodeStatus.COMPLETED)

        ep2 = Episode.create(session_id="u2", routine="planner")
        store.create_episode(ep2)
        store.complete_episode("u2", EpisodeStatus.COMPLETED)
        store.acknowledge_session("u2", "Done.")

        results = store.list_unacknowledged(by="session")
        assert len(results) == 1
        assert results[0].session_id == "u1"

    def test_unacknowledged_by_summarizer(self):
        store = EpisodeStore()
        ep1 = Episode.create(session_id="u3", routine="executor")
        store.create_episode(ep1)
        store.complete_episode("u3", EpisodeStatus.COMPLETED)

        ep2 = Episode.create(session_id="u4", routine="planner")
        store.create_episode(ep2)
        store.complete_episode("u4", EpisodeStatus.COMPLETED)
        store.acknowledge_summarizer("u4", "sessions/2026-04-06/u4.md")

        results = store.list_unacknowledged(by="summarizer")
        assert len(results) == 1
        assert results[0].session_id == "u3"

    def test_excludes_running_episodes(self):
        store = EpisodeStore()
        ep = Episode.create(session_id="u5", routine="executor")
        store.create_episode(ep)
        # Still running — should not appear

        results = store.list_unacknowledged(by="session")
        assert len(results) == 0

    def test_invalid_by_raises(self):
        store = EpisodeStore()
        try:
            store.list_unacknowledged(by="invalid")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestChannelEvents:
    def test_record_and_get(self):
        store = EpisodeStore()
        event = ChannelEvent.create(
            channel="tasks",
            payload={"work_item_id": "wi-1", "action": "ready"},
            source_session_id="sess-100",
        )
        store.record_event(event)

        got = store.get_event(event.id)
        assert got is not None
        assert got.channel == "tasks"
        assert got.payload == {"work_item_id": "wi-1", "action": "ready"}
        assert got.source_session_id == "sess-100"

    def test_get_returns_none(self):
        store = EpisodeStore()
        assert store.get_event("nonexistent") is None

    def test_record_without_session(self):
        store = EpisodeStore()
        event = ChannelEvent.create(channel="external_events", payload={"type": "webhook"})
        store.record_event(event)

        got = store.get_event(event.id)
        assert got.source_session_id is None

    def test_list_by_channel(self):
        store = EpisodeStore()
        e1 = ChannelEvent.create(channel="tasks", payload={"a": 1})
        e2 = ChannelEvent.create(channel="completions", payload={"b": 2})
        e3 = ChannelEvent.create(channel="tasks", payload={"c": 3})
        store.record_event(e1)
        store.record_event(e2)
        store.record_event(e3)

        results = store.list_events(channel="tasks")
        assert len(results) == 2
        assert all(e.channel == "tasks" for e in results)

    def test_list_by_time_range(self):
        store = EpisodeStore()
        old = ChannelEvent.create(channel="tasks", payload={})
        old.timestamp = _ts(-60)
        store.record_event(old)

        recent = ChannelEvent.create(channel="tasks", payload={})
        recent.timestamp = _ts(-5)
        store.record_event(recent)

        results = store.list_events(since=_ts(-10), until=_ts(1))
        assert len(results) == 1

    def test_list_respects_limit(self):
        store = EpisodeStore()
        for i in range(5):
            store.record_event(ChannelEvent.create(channel="tasks", payload={"i": i}))

        results = store.list_events(limit=3)
        assert len(results) == 3

    def test_list_all(self):
        store = EpisodeStore()
        store.record_event(ChannelEvent.create(channel="a", payload={}))
        store.record_event(ChannelEvent.create(channel="b", payload={}))

        results = store.list_events()
        assert len(results) == 2
