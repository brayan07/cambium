"""Tests for the routine runner."""

from pathlib import Path

from cambium.adapters.base import AdapterInstance, AdapterInstanceRegistry, AdapterType, RunResult
from cambium.models.message import Message
from cambium.models.routine import Routine
from cambium.runner.routine_runner import RoutineRunner


class FakeAdapter(AdapterType):
    name = "fake"

    def __init__(self):
        self.last_call = None

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, on_raw_event=None, cwd=None):
        self.last_call = {
            "instance": instance,
            "user_message": user_message,
            "session_id": session_id,
            "token": session_token,
            "api_url": api_base_url,
            "cwd": cwd,
        }
        return RunResult(success=True, output=f"[fake] ran {instance.name}",
                         session_id=session_id)


class TestRoutineRunner:
    def _make_runner(self, tmp_path: Path) -> tuple[RoutineRunner, FakeAdapter]:
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        (inst_dir / "coordinator.yaml").write_text(
            "name: coordinator\n"
            "adapter_type: fake\n"
            "config:\n"
            "  model: haiku\n"
        )
        adapter = FakeAdapter()
        instance_reg = AdapterInstanceRegistry(inst_dir)
        runner = RoutineRunner(
            adapter_types={"fake": adapter},
            instance_registry=instance_reg,
        )
        return runner, adapter

    def test_send_message_resolves_and_executes(self, tmp_path: Path):
        runner, adapter = self._make_runner(tmp_path)
        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True
        assert adapter.last_call is not None
        assert adapter.last_call["instance"].name == "coordinator"
        assert len(adapter.last_call["token"]) > 0
        assert len(adapter.last_call["session_id"]) == 36  # UUID

    def test_missing_instance_returns_error(self, tmp_path: Path):
        runner, _ = self._make_runner(tmp_path)
        routine = Routine(name="test", adapter_instance="nonexistent", listen=[])
        msg = Message.create(channel="x", payload={}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is False
        assert "not found" in result.error

    def test_missing_adapter_type_returns_error(self, tmp_path: Path):
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        (inst_dir / "bad.yaml").write_text("name: bad\nadapter_type: nonexistent\n")

        instance_reg = AdapterInstanceRegistry(inst_dir)
        runner = RoutineRunner(adapter_types={}, instance_registry=instance_reg)
        routine = Routine(name="test", adapter_instance="bad", listen=[])
        msg = Message.create(channel="x", payload={}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is False
        assert "not found" in result.error

    def test_session_token_contains_routine_name(self, tmp_path: Path):
        import jwt as pyjwt
        from cambium.server.auth import _SIGNING_KEY

        runner, adapter = self._make_runner(tmp_path)
        routine = Routine(name="my-routine", adapter_instance="coordinator", listen=[])
        msg = Message.create(channel="x", payload={}, source="test")

        runner.send_message(routine, msg)
        token = adapter.last_call["token"]
        claims = pyjwt.decode(token, _SIGNING_KEY, algorithms=["HS256"])
        assert claims["routine"] == "my-routine"
        assert "session" in claims

    def test_session_persisted_when_store_provided(self, tmp_path: Path):
        from cambium.session.store import SessionStore

        runner, adapter = self._make_runner(tmp_path)
        runner.session_store = SessionStore()

        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True

        # Session should exist in store
        session = runner.session_store.get_session(result.session_id)
        assert session is not None
        assert session.routine_name == "coordinator"
        assert session.status.value == "completed"

        # Messages should be stored
        messages = runner.session_store.get_messages(result.session_id)
        assert len(messages) == 2  # user + assistant
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_session_working_dir_created_and_passed(self, tmp_path: Path):
        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        (inst_dir / "coordinator.yaml").write_text(
            "name: coordinator\nadapter_type: fake\nconfig:\n  model: haiku\n"
        )
        adapter = FakeAdapter()
        instance_reg = AdapterInstanceRegistry(inst_dir)
        runner = RoutineRunner(
            adapter_types={"fake": adapter},
            instance_registry=instance_reg,
            user_dir=tmp_path,
        )
        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True

        # Session working dir should exist
        session_dir = tmp_path / "data" / "sessions" / adapter.last_call["session_id"]
        assert session_dir.is_dir()

        # cwd should have been passed to adapter
        assert adapter.last_call["cwd"] == session_dir

    def test_no_session_dir_without_user_dir(self, tmp_path: Path):
        runner, adapter = self._make_runner(tmp_path)
        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True
        assert adapter.last_call["cwd"] is None

    def test_completed_session_reactivated_on_new_message(self, tmp_path: Path):
        from cambium.session.model import Session, SessionOrigin, SessionStatus
        from cambium.session.store import SessionStore

        runner, adapter = self._make_runner(tmp_path)
        store = SessionStore()
        runner.session_store = store

        # Create a completed session
        session = Session.create(
            origin=SessionOrigin.USER,
            routine_name="coordinator",
            adapter_instance_name="coordinator",
        )
        store.create_session(session)
        store.update_status(session.id, SessionStatus.COMPLETED)
        assert store.get_session(session.id).status == SessionStatus.COMPLETED

        # Send a message to the completed session
        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        result = runner.send_message(
            routine, session_id=session.id, user_message="follow-up question",
        )
        assert result.success is True

        # Session should be completed again (runner sets final status)
        got = store.get_session(session.id)
        assert got.status == SessionStatus.COMPLETED

        # Messages should include the new user message
        messages = store.get_messages(session.id)
        assert any(m.content == "follow-up question" for m in messages)

    def test_failed_session_reactivated_on_new_message(self, tmp_path: Path):
        from cambium.session.model import Session, SessionOrigin, SessionStatus
        from cambium.session.store import SessionStore

        runner, adapter = self._make_runner(tmp_path)
        store = SessionStore()
        runner.session_store = store

        session = Session.create(
            origin=SessionOrigin.USER,
            routine_name="coordinator",
            adapter_instance_name="coordinator",
        )
        store.create_session(session)
        store.update_status(session.id, SessionStatus.FAILED)

        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        result = runner.send_message(
            routine, session_id=session.id, user_message="retry",
        )
        assert result.success is True

    def test_resume_session_with_existing_id(self, tmp_path: Path):
        runner, adapter = self._make_runner(tmp_path)
        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg, session_id="existing-session-id")
        assert result.success is True
        assert adapter.last_call["session_id"] == "existing-session-id"
