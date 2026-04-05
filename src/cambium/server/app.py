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
from cambium.mcp.file_registry import FileRegistry
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner
from cambium.server.auth import authenticate, verify_session_token
from cambium.server import sessions as sessions_module
from cambium.server import work_items as work_items_module
from cambium.session.broadcaster import BroadcasterRegistry
from cambium.session.store import SessionStore
from cambium.work_item.service import WorkItemService
from cambium.work_item.store import WorkItemStore

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
    """Validate JWT and return claims. Delegates to auth.authenticate."""
    return authenticate(authorization)


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

    # Work item store + service (separate DB)
    if db_path == ":memory:":
        wi_db_path = ":memory:"
    else:
        wi_db_path = str(Path(db_path).parent / "work_items.db")
    work_item_store = WorkItemStore(wi_db_path)
    work_item_service = WorkItemService(store=work_item_store, queue=queue)

    # Configure work item endpoints
    work_items_module.configure(service=work_item_service)

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
app.include_router(work_items_module.router)


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
