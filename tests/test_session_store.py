"""Tests for session store."""

from datetime import datetime, timezone, timedelta

from cambium.session.model import Session, SessionMessage, SessionStatus, SessionOrigin
from cambium.session.store import SessionStore


class TestSessionStore:
    def test_create_and_get_session(self):
        store = SessionStore()
        session = Session.create(
            origin=SessionOrigin.USER,
            routine_name="interlocutor",
            adapter_instance_name="interlocutor",
        )
        store.create_session(session)
        got = store.get_session(session.id)
        assert got is not None
        assert got.id == session.id
        assert got.origin == SessionOrigin.USER
        assert got.status == SessionStatus.CREATED
        assert got.routine_name == "interlocutor"

    def test_get_missing_session_returns_none(self):
        store = SessionStore()
        assert store.get_session("nonexistent") is None

    def test_update_status(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.SYSTEM)
        store.create_session(session)

        store.update_status(session.id, SessionStatus.ACTIVE)
        got = store.get_session(session.id)
        assert got.status == SessionStatus.ACTIVE

        store.update_status(session.id, SessionStatus.COMPLETED)
        got = store.get_session(session.id)
        assert got.status == SessionStatus.COMPLETED

    def test_list_sessions(self):
        store = SessionStore()
        for i in range(3):
            s = Session.create(origin=SessionOrigin.SYSTEM, routine_name=f"r{i}")
            store.create_session(s)
        s = Session.create(origin=SessionOrigin.USER)
        store.create_session(s)

        all_sessions = store.list_sessions()
        assert len(all_sessions) == 4

        system_sessions = store.list_sessions(origin=SessionOrigin.SYSTEM)
        assert len(system_sessions) == 3

        user_sessions = store.list_sessions(origin=SessionOrigin.USER)
        assert len(user_sessions) == 1

    def test_list_sessions_by_status(self):
        store = SessionStore()
        s1 = Session.create(origin=SessionOrigin.SYSTEM)
        s2 = Session.create(origin=SessionOrigin.SYSTEM)
        store.create_session(s1)
        store.create_session(s2)
        store.update_status(s1.id, SessionStatus.COMPLETED)

        completed = store.list_sessions(status=SessionStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].id == s1.id

    def test_list_sessions_limit(self):
        store = SessionStore()
        for _ in range(10):
            store.create_session(Session.create(origin=SessionOrigin.SYSTEM))
        assert len(store.list_sessions(limit=3)) == 3


class TestSessionMessages:
    def test_add_and_get_messages(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)

        m1 = SessionMessage.create(session.id, "user", "Hello", sequence=0)
        m2 = SessionMessage.create(session.id, "assistant", "Hi there", sequence=1)
        store.add_message(m1)
        store.add_message(m2)

        messages = store.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there"

    def test_get_messages_after_sequence(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)

        for i in range(5):
            store.add_message(
                SessionMessage.create(session.id, "user", f"msg {i}", sequence=i)
            )

        messages = store.get_messages(session.id, after_sequence=2)
        assert len(messages) == 2
        assert messages[0].sequence == 3
        assert messages[1].sequence == 4

    def test_next_sequence(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)

        assert store.next_sequence(session.id) == 0

        store.add_message(SessionMessage.create(session.id, "user", "a", sequence=0))
        assert store.next_sequence(session.id) == 1

        store.add_message(SessionMessage.create(session.id, "assistant", "b", sequence=1))
        assert store.next_sequence(session.id) == 2

    def test_messages_ordered_by_sequence(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)

        # Insert out of order
        store.add_message(SessionMessage.create(session.id, "assistant", "second", sequence=1))
        store.add_message(SessionMessage.create(session.id, "user", "first", sequence=0))

        messages = store.get_messages(session.id)
        assert messages[0].sequence == 0
        assert messages[1].sequence == 1

    def test_update_metadata_merges_keys(self):
        store = SessionStore()
        session = Session.create(
            origin=SessionOrigin.SYSTEM,
            metadata={"trigger": "events", "message_id": "abc"},
        )
        store.create_session(session)

        store.update_metadata(session.id, {"reflected_through_sequence": 15})

        got = store.get_session(session.id)
        assert got.metadata["trigger"] == "events"
        assert got.metadata["message_id"] == "abc"
        assert got.metadata["reflected_through_sequence"] == 15

    def test_update_metadata_overwrites_existing_key(self):
        store = SessionStore()
        session = Session.create(
            origin=SessionOrigin.SYSTEM,
            metadata={"reflected_through_sequence": 5},
        )
        store.create_session(session)

        store.update_metadata(session.id, {"reflected_through_sequence": 20})

        got = store.get_session(session.id)
        assert got.metadata["reflected_through_sequence"] == 20

    def test_update_metadata_nonexistent_session(self):
        store = SessionStore()
        # Should not raise
        store.update_metadata("nonexistent", {"key": "value"})

    def test_metadata_persisted(self):
        store = SessionStore()
        session = Session.create(
            origin=SessionOrigin.SYSTEM,
            metadata={"trigger_message_id": "abc-123"},
        )
        store.create_session(session)

        got = store.get_session(session.id)
        assert got.metadata["trigger_message_id"] == "abc-123"

        msg = SessionMessage.create(
            session.id, "assistant", "done",
            metadata={"tokens": 150, "model": "opus"},
        )
        store.add_message(msg)

        messages = store.get_messages(session.id)
        assert messages[0].metadata["tokens"] == 150


class TestSessionActivityTracking:
    """Tests for touch(), add_message updated_at refresh, and reap interaction."""

    def test_touch_updates_updated_at(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)
        original = store.get_session(session.id).updated_at

        store.touch(session.id)

        got = store.get_session(session.id)
        assert got.updated_at >= original

    def test_add_message_updates_session_updated_at(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)
        original = store.get_session(session.id).updated_at

        msg = SessionMessage.create(session.id, "user", "hello", sequence=0)
        store.add_message(msg)

        got = store.get_session(session.id)
        assert got.updated_at >= original

    def test_reap_spares_recently_touched_session(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)
        store.update_status(session.id, SessionStatus.ACTIVE)

        # Backdate updated_at to make it look idle
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        store._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (old_time, session.id),
        )
        store._conn.commit()

        # Touch to refresh — simulates a keepalive
        store.touch(session.id)

        reaped = store.reap_idle_sessions(idle_seconds=600)
        assert len(reaped) == 0
        assert store.get_session(session.id).status == SessionStatus.ACTIVE

    def test_reap_spares_session_with_recent_message(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)
        store.update_status(session.id, SessionStatus.ACTIVE)

        # Backdate updated_at
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        store._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (old_time, session.id),
        )
        store._conn.commit()

        # Add a message — should refresh updated_at
        msg = SessionMessage.create(session.id, "user", "still here", sequence=0)
        store.add_message(msg)

        reaped = store.reap_idle_sessions(idle_seconds=600)
        assert len(reaped) == 0
        assert store.get_session(session.id).status == SessionStatus.ACTIVE

    def test_reap_still_catches_truly_idle_sessions(self):
        store = SessionStore()
        session = Session.create(origin=SessionOrigin.USER)
        store.create_session(session)
        store.update_status(session.id, SessionStatus.ACTIVE)

        # Backdate updated_at and don't touch or add messages
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        store._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (old_time, session.id),
        )
        store._conn.commit()

        reaped = store.reap_idle_sessions(idle_seconds=600)
        assert len(reaped) == 1
        assert reaped[0].id == session.id
        assert store.get_session(session.id).status == SessionStatus.COMPLETED
