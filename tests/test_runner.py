"""Tests for the routine runner."""

from pathlib import Path

from cambium.adapters.base import AdapterInstance, AdapterInstanceRegistry, AdapterType, RunResult, Usage
from cambium.models.message import Message
from cambium.models.routine import Routine
from cambium.runner.routine_runner import RoutineRunner


class FakeAdapter(AdapterType):
    name = "fake"

    def __init__(self, usage: Usage | None = None):
        self.last_call = None
        self._usage = usage

    def send_message(self, instance, user_message, session_id, session_token="",
                     api_base_url="", live=True, on_event=None, on_raw_event=None,
                     cwd=None, resume=False):
        self.last_call = {
            "instance": instance,
            "user_message": user_message,
            "session_id": session_id,
            "token": session_token,
            "api_url": api_base_url,
            "cwd": cwd,
            "resume": resume,
        }
        return RunResult(success=True, output=f"[fake] ran {instance.name}",
                         session_id=session_id, usage=self._usage)


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

        # Adapter should have been told to resume
        assert adapter.last_call["resume"] is True

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
        assert adapter.last_call["resume"] is True

    def test_new_session_does_not_resume(self, tmp_path: Path):
        from cambium.session.store import SessionStore

        runner, adapter = self._make_runner(tmp_path)
        runner.session_store = SessionStore()

        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True
        assert adapter.last_call["resume"] is False

    def test_resume_session_with_existing_id(self, tmp_path: Path):
        runner, adapter = self._make_runner(tmp_path)
        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"goal": "test"}, source="test")

        result = runner.send_message(routine, msg, session_id="existing-session-id")
        assert result.success is True
        assert adapter.last_call["session_id"] == "existing-session-id"


class TestUsagePersistence:
    """Tests for token usage tracking through the runner → session metadata pipeline."""

    def _make_runner_with_store(self, tmp_path: Path, usage: Usage | None = None):
        from cambium.session.store import SessionStore

        inst_dir = tmp_path / "instances"
        inst_dir.mkdir()
        (inst_dir / "coordinator.yaml").write_text(
            "name: coordinator\nadapter_type: fake\nconfig:\n  model: haiku\n"
        )
        adapter = FakeAdapter(usage=usage)
        instance_reg = AdapterInstanceRegistry(inst_dir)
        store = SessionStore()
        runner = RoutineRunner(
            adapter_types={"fake": adapter},
            instance_registry=instance_reg,
        )
        runner.session_store = store
        return runner, adapter, store

    def test_usage_persisted_to_session_metadata(self, tmp_path: Path):
        usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=200,
                      cache_creation_tokens=50, cost_usd=0.042)
        runner, _, store = self._make_runner_with_store(tmp_path, usage=usage)

        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"test": True}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True

        session = store.get_session(result.session_id)
        assert session is not None
        u = session.metadata["usage"]
        assert u["input_tokens"] == 1000
        assert u["output_tokens"] == 500
        assert u["cache_read_tokens"] == 200
        assert u["cache_creation_tokens"] == 50
        assert u["cost_usd"] == 0.042

    def test_usage_accumulates_across_turns(self, tmp_path: Path):
        usage = Usage(input_tokens=1000, output_tokens=500, cost_usd=0.05)
        runner, _, store = self._make_runner_with_store(tmp_path, usage=usage)

        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"test": True}, source="test")

        # First invocation creates the session
        result1 = runner.send_message(routine, msg)
        session_id = result1.session_id

        # Second invocation on the same session
        result2 = runner.send_message(
            routine, session_id=session_id, user_message="follow-up",
        )
        assert result2.success is True

        session = store.get_session(session_id)
        u = session.metadata["usage"]
        assert u["input_tokens"] == 2000
        assert u["output_tokens"] == 1000
        assert u["cost_usd"] == 0.1

    def test_none_usage_skips_metadata_update(self, tmp_path: Path):
        runner, _, store = self._make_runner_with_store(tmp_path, usage=None)

        routine = Routine(name="coordinator", adapter_instance="coordinator", listen=["events"])
        msg = Message.create(channel="events", payload={"test": True}, source="test")

        result = runner.send_message(routine, msg)
        assert result.success is True

        session = store.get_session(result.session_id)
        assert "usage" not in session.metadata
