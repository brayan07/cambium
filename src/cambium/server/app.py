"""Cambium API server — channel-based pub/sub with JWT session auth."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import jwt
import uvicorn
import yaml
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from cambium.adapters.base import AdapterInstanceRegistry
from cambium.adapters.claude_code import ClaudeCodeAdapter
from cambium.consumer.loop import ConsumerLoop
from cambium.mcp.file_registry import FileRegistry
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner
from cambium.server.auth import verify_session_token
from cambium.server import sessions as sessions_module
from cambium.session.broadcaster import BroadcasterRegistry
from cambium.session.store import SessionStore
from cambium.sources.base import EventSource

log = logging.getLogger(__name__)


# --- Pydantic request/response models ---


class PublishRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


class PublishResponse(BaseModel):
    id: str
    channel: str
    status: str


class ChannelPermissions(BaseModel):
    routine: str
    listen: list[str]
    publish: list[str]


class QueueStatus(BaseModel):
    pending: int
    subscribed_channels: list[str]


class HealthResponse(BaseModel):
    status: str
    consumer_running: bool
    pending_messages: int
    sources: int = 0


# --- Server state ---


class CambiumServer:
    def __init__(
        self,
        queue: SQLiteQueue,
        routine_registry: RoutineRegistry,
        routine_runner: RoutineRunner,
        consumer: ConsumerLoop,
        sources: list[EventSource] | None = None,
        source_poll_interval: float = 10.0,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.routine_runner = routine_runner
        self.consumer = consumer
        self.sources = sources or []
        self.source_poll_interval = source_poll_interval
        self._consumer_task: asyncio.Task | None = None
        self._source_task: asyncio.Task | None = None

    async def start_consumer(self) -> None:
        self._consumer_task = asyncio.create_task(self._run_consumer())
        log.info("Consumer loop started")
        if self.sources:
            self._source_task = asyncio.create_task(self._run_sources())
            log.info("Source poller started (%d sources)", len(self.sources))

    async def stop_consumer(self) -> None:
        for task in [self._consumer_task, self._source_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._consumer_task = None
        self._source_task = None
        log.info("Consumer and source loops stopped")

    @property
    def consumer_running(self) -> bool:
        return self._consumer_task is not None and not self._consumer_task.done()

    async def _run_consumer(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            try:
                results = await loop.run_in_executor(None, self.consumer.tick)
                for r in results:
                    status = "OK" if r.success else "FAIL"
                    log.info(f"Run result: {status} — {r.output[:100] if r.output else r.error}")
            except Exception:
                log.exception("Consumer tick error")
            await asyncio.sleep(self.consumer.poll_interval)

    async def _run_sources(self) -> None:
        """Poll all registered event sources periodically."""
        loop = asyncio.get_event_loop()
        while True:
            for source in self.sources:
                try:
                    count = await loop.run_in_executor(None, source.poll)
                    if count:
                        log.info("Source %s emitted %d events", type(source).__name__, count)
                except Exception:
                    log.exception("Source poll error (%s)", type(source).__name__)
            await asyncio.sleep(self.source_poll_interval)


# --- Module-level state ---

_server: CambiumServer | None = None


def _get_routine_permissions(routine_name: str) -> tuple[list[str], list[str]]:
    """Get listen/publish permissions for a routine."""
    if _server is None:
        return [], []
    routine = _server.routine_registry.get(routine_name)
    if routine is None:
        return [], []
    return routine.listen, routine.publish


def _authenticate(authorization: str | None) -> dict:
    """Validate JWT and return claims. Raises HTTPException on failure."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Accept "Bearer <token>" or raw token
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_session_token(token)
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def _load_config(user_dir: Path) -> dict[str, Any]:
    """Load config.yaml from the user directory."""
    config_path = user_dir / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _build_sources(config: dict[str, Any], queue: SQLiteQueue) -> list[EventSource]:
    """Instantiate event sources from config."""
    sources: list[EventSource] = []
    sources_config = config.get("sources", {})

    if "clickup" in sources_config:
        from cambium.sources.clickup_poller import ClickUpPoller
        poller = ClickUpPoller(sources_config["clickup"], queue)
        sources.append(poller)
        log.info("ClickUp poller configured (team=%s)", sources_config["clickup"].get("team_id"))

    return sources


def build_server(
    db_path: str | None = None,
    user_dir: Path | None = None,
    live: bool = False,
    poll_interval: float = 2.0,
    api_base_url: str = "http://127.0.0.1:8350",
) -> CambiumServer:
    """Construct all Cambium components and return a CambiumServer.

    All configuration is read from ``user_dir`` (default ``~/.cambium/``).
    Run ``cambium init`` first to seed the user directory from framework defaults.
    """
    user_dir = user_dir or Path.home() / ".cambium"

    # Load user config
    config = _load_config(user_dir)

    # Queue
    if db_path is None:
        db_dir = user_dir / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "cambium.db")
    queue = SQLiteQueue(db_path)

    # Skill registry
    skill_dirs = [user_dir / "adapters" / "claude-code" / "skills"]
    skill_registry = SkillRegistry(*[d for d in skill_dirs if d.exists()])

    # Adapter instances
    instance_dirs = [user_dir / "adapters" / "claude-code" / "instances"]
    instance_registry = AdapterInstanceRegistry(*[d for d in instance_dirs if d.exists()])

    # MCP registry
    mcp_registry = FileRegistry(user_dir / "mcp-servers.json")

    # Adapter types
    claude_adapter = ClaudeCodeAdapter(skill_registry, user_dir=user_dir, mcp_registry=mcp_registry)
    adapter_types = {claude_adapter.name: claude_adapter}

    # Routine registry
    routine_registry = RoutineRegistry(*[d for d in [user_dir / "routines"] if d.exists()])

    # Session store (shares DB with queue)
    session_store = SessionStore(db_path)

    # Broadcaster registry for live streaming
    broadcaster_registry = BroadcasterRegistry()

    # Routine runner
    routine_runner = RoutineRunner(
        adapter_types=adapter_types,
        instance_registry=instance_registry,
        session_store=session_store,
        api_base_url=api_base_url,
        user_dir=user_dir,
    )

    # Configure session endpoints
    sessions_module.configure(
        session_store=session_store,
        broadcaster_registry=broadcaster_registry,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
    )

    # Consumer loop
    consumer = ConsumerLoop(
        queue=queue,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
        broadcaster_registry=broadcaster_registry,
        poll_interval=poll_interval,
        live=live,
    )

    # Event sources
    sources = _build_sources(config, queue) if live else []

    log.info(f"Skills: {skill_registry.names()}")
    log.info(f"Adapter instances: {[i.name for i in instance_registry.all()]}")
    log.info(f"Routines: {[r.name for r in routine_registry.all()]}")
    log.info(f"Sources: {[type(s).__name__ for s in sources]}")
    log.info(f"Queue DB: {db_path}")
    log.info(f"Live mode: {live}")

    return CambiumServer(
        queue=queue,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
        consumer=consumer,
        sources=sources,
        source_poll_interval=config.get("source_poll_interval", 10.0),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _server
    if _server is not None:
        await _server.start_consumer()
    yield
    if _server is not None:
        await _server.stop_consumer()


# --- FastAPI app ---

app = FastAPI(
    title="Cambium",
    description="Personal AI agent skill lifecycle engine",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(sessions_module.router)


def _get_server() -> CambiumServer:
    if _server is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    return _server


# --- Channel endpoints (JWT-protected) ---


@app.post("/channels/{channel}/publish", response_model=PublishResponse, status_code=201)
def publish_to_channel(
    channel: str,
    body: PublishRequest,
    authorization: str | None = Header(default=None),
):
    """Publish a message to a channel. Requires valid session token."""
    server = _get_server()
    claims = _authenticate(authorization)

    routine_name = claims["routine"]
    _, allowed_publish = _get_routine_permissions(routine_name)

    if channel not in allowed_publish:
        raise HTTPException(
            status_code=403,
            detail=f"Routine '{routine_name}' is not allowed to publish to '{channel}'",
        )

    message = Message.create(
        channel=channel,
        payload=body.payload,
        source=routine_name,
    )
    server.queue.publish(message)
    log.info(f"Published to '{channel}' by '{routine_name}' (id={message.id[:8]})")

    return PublishResponse(id=message.id, channel=channel, status="pending")


@app.get("/channels/permissions", response_model=ChannelPermissions)
def get_permissions(authorization: str | None = Header(default=None)):
    """Get channel permissions for the authenticated routine."""
    claims = _authenticate(authorization)
    routine_name = claims["routine"]
    listen, publish = _get_routine_permissions(routine_name)
    return ChannelPermissions(routine=routine_name, listen=listen, publish=publish)


# --- Unauthenticated endpoints ---


@app.post("/channels/{channel}/send", response_model=PublishResponse, status_code=201)
def send_to_channel(channel: str, body: PublishRequest):
    """Publish a message without auth — for external triggers, CLI, and testing."""
    server = _get_server()
    message = Message.create(channel=channel, payload=body.payload, source="external")
    server.queue.publish(message)
    log.info(f"External send to '{channel}' (id={message.id[:8]})")
    return PublishResponse(id=message.id, channel=channel, status="pending")


@app.get("/queue/status", response_model=QueueStatus)
def queue_status():
    server = _get_server()
    return QueueStatus(
        pending=server.queue.pending_count(),
        subscribed_channels=server.routine_registry.subscribed_channels(),
    )


@app.get("/health", response_model=HealthResponse)
def health():
    server = _get_server()
    return HealthResponse(
        status="ok",
        consumer_running=server.consumer_running,
        pending_messages=server.queue.pending_count(),
        sources=len(server.sources),
    )


# --- Entrypoint ---


def run_server(
    host: str = "127.0.0.1",
    port: int = 8350,
    live: bool = False,
    poll_interval: float = 2.0,
    log_level: str = "info",
) -> None:
    global _server
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    _server = build_server(live=live, poll_interval=poll_interval)
    uvicorn.run(app, host=host, port=port, log_level=log_level)
