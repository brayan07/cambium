"""Routine runner — the framework-level orchestrator.

Loads the adapter instance for a routine, creates a session,
issues a session token, and delegates execution to the adapter type.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from cambium.adapters.base import AdapterInstanceRegistry, AdapterType, RunResult
from cambium.models.message import Message
from cambium.models.routine import Routine
from cambium.server.auth import create_session_token
from cambium.session.model import Session, SessionMessage, SessionStatus, SessionType
from cambium.session.store import SessionStore


class RoutineRunner:
    """Resolves adapter instances and executes routines."""

    def __init__(
        self,
        adapter_types: dict[str, AdapterType],
        instance_registry: AdapterInstanceRegistry,
        session_store: SessionStore | None = None,
        api_base_url: str = "http://127.0.0.1:8350",
    ) -> None:
        self.adapter_types = adapter_types
        self.instance_registry = instance_registry
        self.session_store = session_store
        self.api_base_url = api_base_url

    def send_message(
        self,
        routine: Routine,
        message: Message | None = None,
        session_id: str | None = None,
        user_message: str | None = None,
        live: bool = True,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Execute a routine for a given message.

        For one-shot sessions (consumer loop): pass ``message`` and omit
        ``session_id`` — the runner creates a session automatically.

        For interactive sessions (API endpoint): pass ``session_id`` and
        ``user_message`` — the runner reuses the existing session.
        """
        # Resolve adapter instance
        instance = self.instance_registry.get(routine.adapter_instance)
        if instance is None:
            return RunResult(
                success=False,
                output="",
                error=f"Adapter instance not found: {routine.adapter_instance}",
            )

        # Resolve adapter type
        adapter = self.adapter_types.get(instance.adapter_type)
        if adapter is None:
            return RunResult(
                success=False,
                output="",
                error=f"Adapter type not found: {instance.adapter_type}",
            )

        # Create or reuse session
        is_new_session = session_id is None
        if is_new_session:
            session_id = str(uuid.uuid4())

        if self.session_store and is_new_session:
            session = Session.create(
                session_type=SessionType.ONE_SHOT,
                routine_name=routine.name,
                adapter_instance_name=routine.adapter_instance,
                metadata={"trigger_channel": message.channel, "trigger_message_id": message.id} if message else {},
            )
            session.id = session_id
            session.status = SessionStatus.ACTIVE
            self.session_store.create_session(session)
        elif self.session_store and not is_new_session:
            # Interactive session: activate if still in CREATED status
            existing = self.session_store.get_session(session_id)
            if existing and existing.status == SessionStatus.CREATED:
                self.session_store.update_status(session_id, SessionStatus.ACTIVE)

        # Issue session token
        token = create_session_token(routine.name, session_id)

        # Determine the user message text
        if user_message is None:
            # One-shot: build from Message payload
            user_message = json.dumps(message.payload, indent=2) if (message and message.payload) else (message.channel if message else "")

        # Store the user message
        if self.session_store:
            seq = self.session_store.next_sequence(session_id)
            self.session_store.add_message(
                SessionMessage.create(session_id, "user", user_message, sequence=seq)
            )

        # Execute
        result = adapter.send_message(
            instance=instance,
            user_message=user_message,
            session_id=session_id,
            session_token=token,
            api_base_url=self.api_base_url,
            live=live,
            on_event=on_event,
        )

        # Store result and update session
        if self.session_store:
            if result.output:
                seq = self.session_store.next_sequence(session_id)
                self.session_store.add_message(
                    SessionMessage.create(
                        session_id, "assistant", result.output, sequence=seq,
                        metadata={"duration_seconds": result.duration_seconds},
                    )
                )
            if is_new_session:
                status = SessionStatus.COMPLETED if result.success else SessionStatus.FAILED
                self.session_store.update_status(session_id, status)

        return result
