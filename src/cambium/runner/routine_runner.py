"""Routine runner — the framework-level orchestrator.

Loads the adapter instance for a routine, creates a session,
issues a session token, and delegates execution to the adapter type.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable

from cambium.adapters.base import AdapterInstanceRegistry, AdapterType, RunResult
from cambium.episode.model import Episode, EpisodeStatus
from cambium.episode.store import EpisodeStore
from cambium.models.message import Message
from cambium.models.routine import Routine
from cambium.server.auth import create_session_token
from cambium.session.model import Session, SessionMessage, SessionOrigin, SessionStatus, TranscriptEvent
from cambium.session.store import SessionStore


class RoutineRunner:
    """Resolves adapter instances and executes routines."""

    def __init__(
        self,
        adapter_types: dict[str, AdapterType],
        instance_registry: AdapterInstanceRegistry,
        session_store: SessionStore | None = None,
        api_base_url: str = "http://127.0.0.1:8350",
        user_dir: Path | None = None,
    ) -> None:
        self.adapter_types = adapter_types
        self.instance_registry = instance_registry
        self.session_store = session_store
        self.episode_store: EpisodeStore | None = None
        self.api_base_url = api_base_url
        self.user_dir = user_dir

    def send_message(
        self,
        routine: Routine,
        message: Message | None = None,
        session_id: str | None = None,
        user_message: str | None = None,
        live: bool = True,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        store_transcript: bool = True,
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
        resume = False
        if session_id is None:
            session_id = str(uuid.uuid4())

        if self.session_store:
            existing = self.session_store.get_session(session_id)
            if existing is None:
                # New session — create and persist
                session = Session.create(
                    origin=SessionOrigin.SYSTEM,
                    routine_name=routine.name,
                    adapter_instance_name=routine.adapter_instance,
                    metadata={"trigger_channel": message.channel, "trigger_message_id": message.id} if message else {},
                )
                session.id = session_id
                session.status = SessionStatus.ACTIVE
                self.session_store.create_session(session)
            elif existing.status in (SessionStatus.CREATED, SessionStatus.COMPLETED, SessionStatus.FAILED):
                # Activate: new interactive session, or reopened completed/failed session
                self.session_store.update_status(session_id, SessionStatus.ACTIVE)
                # Resume if the session has prior messages (not just CREATED with no history)
                if existing.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
                    resume = True
            elif existing.status == SessionStatus.ACTIVE:
                # Already active (e.g., second message in interactive session)
                resume = True

        # Create episode entry
        if self.episode_store:
            episode = Episode.create(
                session_id=session_id,
                routine=routine.name,
                trigger_event_ids=[message.id] if message else [],
            )
            self.episode_store.create_episode(episode)

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

        # Create session working directory
        session_dir = None
        if self.user_dir:
            session_dir = self.user_dir / "data" / "sessions" / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

        # Build transcript callback — persists adapter-produced TranscriptEvents.
        # The runner never inspects event contents; the adapter owns the translation.
        on_raw_event = None
        _raw_event_count = [0]
        if self.session_store and store_transcript:
            _seq = [self.session_store.next_sequence(session_id)]

            def on_raw_event(te: TranscriptEvent) -> None:
                self.session_store.add_message(
                    SessionMessage.create(
                        session_id,
                        role=te.role,
                        content=te.content,
                        sequence=_seq[0],
                        metadata={"event_type": te.event_type, "raw": te.raw},
                    )
                )
                _seq[0] += 1
                _raw_event_count[0] += 1

        # Execute
        result = adapter.send_message(
            instance=instance,
            user_message=user_message,
            session_id=session_id,
            session_token=token,
            api_base_url=self.api_base_url,
            live=live,
            on_event=on_event,
            on_raw_event=on_raw_event,
            cwd=session_dir,
            resume=resume,
        )

        # If no raw events were captured but we have output, store it as a
        # fallback assistant message (covers adapters that don't emit raw events)
        if self.session_store and result.output and _raw_event_count[0] == 0:
            seq = self.session_store.next_sequence(session_id)
            self.session_store.add_message(
                SessionMessage.create(
                    session_id, "assistant", result.output, sequence=seq,
                    metadata={"duration_seconds": result.duration_seconds, "fallback": True},
                )
            )

        # Update session status
        if self.session_store:
            status = SessionStatus.COMPLETED if result.success else SessionStatus.FAILED
            self.session_store.update_status(session_id, status)

        # Complete episode entry
        if self.episode_store:
            ep_status = EpisodeStatus.COMPLETED if result.success else EpisodeStatus.FAILED
            self.episode_store.complete_episode(session_id, ep_status)

        return result
