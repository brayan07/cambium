"""Cambium API server — channel-based pub/sub with JWT session auth."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import jwt
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from cambium.adapters.base import AdapterInstanceRegistry
from cambium.adapters.claude_code import ClaudeCodeAdapter
from cambium.consumer.loop import ConsumerLoop
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner
from cambium.server.auth import verify_session_token
from cambium.server import sessions as sessions_module
from cambium.session.broadcaster import BroadcasterRegistry
from cambium.session.store import SessionStore

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


# --- Server state ---


class CambiumServer:
    def __init__(
        self,
        queue: SQLiteQueue,
        routine_registry: RoutineRegistry,
        routine_runner: RoutineRunner,
        consumer: ConsumerLoop,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.routine_runner = routine_runner
        self.consumer = consumer
        self._consumer_task: asyncio.Task | None = None

    async def start_consumer(self) -> None:
        self._consumer_task = asyncio.create_task(self._run_consumer())
        log.info("Consumer loop started")

    async def stop_consumer(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
            log.info("Consumer loop stopped")

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


def build_server(
    db_path: str | None = None,
    framework_dir: Path | None = None,
    user_dir: Path | None = None,
    live: bool = False,
    poll_interval: float = 2.0,
    api_base_url: str = "http://127.0.0.1:8350",
) -> CambiumServer:
    """Construct all Cambium components and return a CambiumServer."""
    framework_dir = framework_dir or Path(__file__).parent.parent.parent.parent
    user_dir = user_dir or Path.home() / ".cambium"

    # Queue
    if db_path is None:
        db_dir = user_dir / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "cambium.db")
    queue = SQLiteQueue(db_path)

    # Skill registry (owned by Claude Code adapter type)
    skill_dirs = [framework_dir / "defaults" / "adapters" / "claude-code" / "skills"]
    if (user_dir / "adapters" / "claude-code" / "skills").exists():
        skill_dirs.append(user_dir / "adapters" / "claude-code" / "skills")
    # Also check legacy locations for now
    if (framework_dir / "defaults" / "skills").exists():
        skill_dirs.insert(0, framework_dir / "defaults" / "skills")
    skill_registry = SkillRegistry(*skill_dirs)

    # Adapter instances
    instance_dirs = []
    adapter_instances_dir = framework_dir / "defaults" / "adapters" / "claude-code" / "instances"
    if adapter_instances_dir.exists():
        instance_dirs.append(adapter_instances_dir)
    if (user_dir / "adapters" / "claude-code" / "instances").exists():
        instance_dirs.append(user_dir / "adapters" / "claude-code" / "instances")
    instance_registry = AdapterInstanceRegistry(*instance_dirs)

    # Adapter types
    claude_adapter = ClaudeCodeAdapter(skill_registry, framework_dir=framework_dir)
    adapter_types = {claude_adapter.name: claude_adapter}

    # Routine registry
    routine_dirs = [framework_dir / "defaults" / "routines"]
    if (user_dir / "routines").exists():
        routine_dirs.append(user_dir / "routines")
    routine_registry = RoutineRegistry(*routine_dirs)

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
        poll_interval=poll_interval,
        live=live,
    )

    log.info(f"Skills: {skill_registry.names()}")
    log.info(f"Adapter instances: {[i.name for i in instance_registry.all()]}")
    log.info(f"Routines: {[r.name for r in routine_registry.all()]}")
    log.info(f"Queue DB: {db_path}")
    log.info(f"Live mode: {live}")

    return CambiumServer(
        queue=queue,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
        consumer=consumer,
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
