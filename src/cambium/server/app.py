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

from cambium.memory.service import MemoryService
from cambium.adapters.base import AdapterInstanceRegistry
from cambium.adapters.claude_code import ClaudeCodeAdapter
from cambium.consumer.loop import ConsumerLoop
from cambium.episode.model import ChannelEvent
from cambium.episode.store import EpisodeStore
from cambium.mcp.file_registry import FileRegistry
from cambium.models.message import Message
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.routine_runner import RoutineRunner
from cambium.server.auth import authenticate, verify_session_token
from cambium.request.service import RequestService
from cambium.request.store import RequestStore
from cambium.metric.model import load_metrics
from cambium.metric.runner import MetricRunner
from cambium.metric.service import MetricService
from cambium.metric.store import ReadingStore
from cambium.server import auth as auth_module
from cambium.server import episodes as episodes_module
from cambium.server import metrics as metrics_module
from cambium.server import requests as requests_module
from cambium.server import sessions as sessions_module
from cambium.server import work_items as work_items_module
from cambium.session.broadcaster import BroadcasterRegistry
from cambium.session.store import SessionStore
from cambium.timer.loop import TimerLoop
from cambium.timer.model import load_timers
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
    in_flight_messages: int = 0


# --- Server state ---


class CambiumServer:
    def __init__(
        self,
        queue: SQLiteQueue,
        routine_registry: RoutineRegistry,
        routine_runner: RoutineRunner,
        consumer: ConsumerLoop,
        timer_loop: TimerLoop | None = None,
        request_service: RequestService | None = None,
        session_store=None,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.routine_runner = routine_runner
        self.consumer = consumer
        self.timer_loop = timer_loop
        self.request_service = request_service
        self.session_store = session_store
        self._consumer_task: asyncio.Task | None = None
        self._timer_task: asyncio.Task | None = None

    async def start_consumer(self) -> None:
        self._consumer_task = asyncio.create_task(self._run_consumer())
        log.info("Consumer loop started")
        if self.timer_loop and self.timer_loop.timers:
            self._timer_task = asyncio.create_task(self._run_timers())
            log.info(f"Timer loop started ({len(self.timer_loop.timers)} timers)")

    async def stop_consumer(self) -> None:
        for task, name in [(self._timer_task, "Timer"), (self._consumer_task, "Consumer")]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                log.info(f"{name} loop stopped")
        self._consumer_task = None
        self._timer_task = None

    @property
    def consumer_running(self) -> bool:
        return self._consumer_task is not None and not self._consumer_task.done()

    async def _run_consumer(self) -> None:
        loop = asyncio.get_event_loop()
        reap_counter = 0
        while True:
            try:
                results = await loop.run_in_executor(None, self.consumer.tick)
                for r in results:
                    status = "OK" if r.success else "FAIL"
                    log.info(f"Run result: {status} — {r.output[:100] if r.output else r.error}")
            except Exception:
                log.exception("Consumer tick error")

            # Reap idle interactive sessions every ~60s (30 ticks × 2s poll)
            reap_counter += 1
            if reap_counter >= 30:
                reap_counter = 0
                try:
                    await loop.run_in_executor(None, self._reap_idle_sessions)
                except Exception:
                    log.exception("Session reaper error")

            await asyncio.sleep(self.consumer.poll_interval)

    def _reap_idle_sessions(self) -> None:
        """Mark idle interactive sessions as completed and notify the summarizer."""
        if not self.session_store:
            return
        reaped = self.session_store.reap_idle_sessions(idle_seconds=600)
        for session in reaped:
            self.queue.publish(Message.create(
                channel="sessions_completed",
                payload={
                    "session_id": session.id,
                    "routine_name": session.routine_name,
                    "success": True,
                    "trigger_channel": "idle_timeout",
                },
                source="system",
            ))
            log.info(f"Reaped idle session {session.id[:8]} ({session.routine_name})")

    async def _run_timers(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            try:
                fired = await loop.run_in_executor(None, self.timer_loop.tick)
                if fired:
                    log.info(f"Timers fired: {fired}")
            except Exception:
                log.exception("Timer tick error")
            await asyncio.sleep(60)  # Cron resolution is 1 minute


# --- Module-level state ---

_server: CambiumServer | None = None
_episode_store: EpisodeStore | None = None


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


def _resolve_config_dir(repo_dir: Path) -> Path:
    """Find the config root within a repo directory.

    Supports two layouts:
    - Combined repo: ``repo_dir/defaults/routines/`` (framework repo with defaults/)
    - Legacy init: ``repo_dir/routines/`` (old cambium init flat copy)
    """
    if (repo_dir / "defaults" / "routines").exists():
        return repo_dir / "defaults"
    return repo_dir


def _cleanup_zombie_sessions(session_store) -> None:
    """Mark any 'active' or 'created' sessions as completed on startup.

    If the server is starting, no sessions can be legitimately running —
    their processes died with the previous server instance.
    """
    from cambium.session.model import SessionStatus

    zombies = session_store.list_sessions(status=SessionStatus.ACTIVE, limit=500)
    zombies += session_store.list_sessions(status=SessionStatus.CREATED, limit=500)
    for s in zombies:
        session_store.update_status(s.id, SessionStatus.COMPLETED)
    if zombies:
        log.info(f"Cleaned up {len(zombies)} zombie session(s) from previous server run")


def build_server(
    db_path: str | None = None,
    user_dir: Path | None = None,
    repo_dir: Path | None = None,
    data_dir: Path | None = None,
    live: bool = False,
    poll_interval: float = 2.0,
    api_base_url: str = "http://127.0.0.1:8350",
) -> CambiumServer:
    """Construct all Cambium components and return a CambiumServer.

    Configuration is read from ``repo_dir`` (code + configs). Runtime state
    (database, memory, sessions) is written to ``data_dir``.

    For backward compatibility, ``user_dir`` can be passed instead — it sets
    both ``repo_dir`` and ``data_dir`` to the same path (the legacy layout
    where ``~/.cambium/`` holds everything).

    Defaults:
    - ``repo_dir``: current working directory
    - ``data_dir``: ``~/.cambium/``
    """
    # Backward compat: user_dir sets both if the new params aren't given
    if user_dir is not None:
        repo_dir = repo_dir or user_dir
        data_dir = data_dir or user_dir
    else:
        repo_dir = repo_dir or Path.cwd()
        data_dir = data_dir or Path.home() / ".cambium"

    config_dir = _resolve_config_dir(repo_dir)

    # Queue
    if db_path is None:
        db_dir = data_dir / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "cambium.db")
    queue = SQLiteQueue(db_path)

    # Skill registry
    skill_dirs = [config_dir / "adapters" / "claude-code" / "skills"]
    skill_registry = SkillRegistry(*[d for d in skill_dirs if d.exists()])

    # Adapter instances
    instance_dirs = [config_dir / "adapters" / "claude-code" / "instances"]
    instance_registry = AdapterInstanceRegistry(*[d for d in instance_dirs if d.exists()])

    # MCP registry
    mcp_registry = FileRegistry(config_dir / "mcp-servers.json")

    # Adapter types — pass config_dir so prompts resolve correctly
    claude_adapter = ClaudeCodeAdapter(skill_registry, user_dir=config_dir, mcp_registry=mcp_registry, data_dir=data_dir)
    adapter_types = {claude_adapter.name: claude_adapter}

    # Routine registry
    routine_registry = RoutineRegistry(*[d for d in [config_dir / "routines"] if d.exists()])

    # Session store (shares DB with queue)
    session_store = SessionStore(db_path)

    # Clean up zombie sessions — any session still "active" from before this
    # server started has no running process behind it.
    _cleanup_zombie_sessions(session_store)

    # Episode store (shares DB with queue + sessions)
    episode_store = EpisodeStore(db_path)

    # Broadcaster registry for live streaming
    broadcaster_registry = BroadcasterRegistry()

    # Routine runner — data_dir for session working directories
    routine_runner = RoutineRunner(
        adapter_types=adapter_types,
        instance_registry=instance_registry,
        session_store=session_store,
        api_base_url=api_base_url,
        user_dir=data_dir,
    )
    routine_runner.episode_store = episode_store

    # Work item store + service (separate DB)
    if db_path == ":memory:":
        wi_db_path = ":memory:"
    else:
        wi_db_path = str(Path(db_path).parent / "work_items.db")
    work_item_store = WorkItemStore(wi_db_path)
    work_item_service = WorkItemService(store=work_item_store, queue=queue)

    # Request store + service (separate DB)
    if db_path == ":memory:":
        req_db_path = ":memory:"
    else:
        req_db_path = str(Path(db_path).parent / "requests.db")
    request_store = RequestStore(req_db_path)
    request_service = RequestService(store=request_store, queue=queue)

    # Metric store + service + runner (separate DB)
    metric_configs = load_metrics(config_dir / "metrics.yaml")
    if db_path == ":memory:":
        metric_db_path = ":memory:"
    else:
        metric_db_path = str(Path(db_path).parent / "metrics.db")
    reading_store = ReadingStore(metric_db_path)
    metric_service = MetricService(store=reading_store, queue=queue, metrics=metric_configs)
    metric_runner = MetricRunner(
        metrics=metric_configs,
        store=reading_store,
        request_service=request_service,
        queue=queue,
        config_dir=config_dir,
        api_base_url=api_base_url,
    )

    # Startup reconciliation: log orphaned readings
    known_names = {m.name for m in metric_configs}
    orphans = reading_store.get_orphaned_metric_names(known_names)
    if orphans:
        log.warning("Orphaned metric readings (no config): %s", orphans)

    # Configure episode endpoints
    episodes_module.configure(episode_store=episode_store)

    # Configure work item endpoints
    work_items_module.configure(service=work_item_service)

    # Configure request endpoints
    requests_module.configure(service=request_service)

    # Configure metric endpoints
    metrics_module.configure(service=metric_service)

    # Configure session endpoints
    sessions_module.configure(
        session_store=session_store,
        broadcaster_registry=broadcaster_registry,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
        queue=queue,
    )

    # Consumer loop
    consumer = ConsumerLoop(
        queue=queue,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
        broadcaster_registry=broadcaster_registry,
        poll_interval=poll_interval,
        live=live,
        request_service=request_service,
        session_store=session_store,
        metric_runner=metric_runner,
    )

    # Set module-level episode store for publish endpoint event recording
    global _episode_store
    _episode_store = episode_store

    # Memory service — lives in data_dir
    memory_dir = data_dir / "memory"
    memory_service = MemoryService(memory_dir)
    log.info(f"Memory directory: {memory_service.path}")

    # Timer loop — config lives in repo
    timers = load_timers(config_dir / "timers.yaml")
    timer_loop = TimerLoop(timers, queue) if timers else None

    # Configure terminal PTY bridge with directory paths
    terminal_module.configure(repo_dir=repo_dir, data_dir=data_dir, session_store=session_store)

    log.info(f"Config dir: {config_dir}")
    log.info(f"Data dir: {data_dir}")
    log.info(f"Skills: {skill_registry.names()}")
    log.info(f"Adapter instances: {[i.name for i in instance_registry.all()]}")
    log.info(f"Routines: {[r.name for r in routine_registry.all()]}")
    log.info(f"Timers: {[t.name for t in timers]}")
    log.info(f"Queue DB: {db_path}")
    log.info(f"Live mode: {live}")

    return CambiumServer(
        queue=queue,
        routine_registry=routine_registry,
        routine_runner=routine_runner,
        consumer=consumer,
        timer_loop=timer_loop,
        request_service=request_service,
        session_store=session_store,
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

from cambium.server import terminal as terminal_module

app.include_router(auth_module.router)
app.include_router(episodes_module.router)
app.include_router(metrics_module.router)
app.include_router(requests_module.router)
app.include_router(sessions_module.router)
app.include_router(work_items_module.router)
app.include_router(terminal_module.router)


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

    # Record channel event in episodic index
    if _episode_store:
        session_id = claims.get("session")
        event = ChannelEvent.create(
            channel=channel,
            payload=body.payload,
            source_session_id=session_id,
        )
        _episode_store.record_event(event)
        if session_id:
            _episode_store.append_emitted_event(session_id, event.id)

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

    # Record channel event in episodic index (no session association)
    if _episode_store:
        event = ChannelEvent.create(channel=channel, payload=body.payload)
        _episode_store.record_event(event)

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
        in_flight_messages=server.queue.in_flight_count(),
    )


# --- Entrypoint ---


def run_server(
    host: str = "127.0.0.1",
    port: int = 8350,
    live: bool = False,
    poll_interval: float = 2.0,
    log_level: str = "info",
    repo_dir: Path | None = None,
    data_dir: Path | None = None,
    db_path: str | None = None,
) -> None:
    global _server
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    _server = build_server(
        live=live,
        poll_interval=poll_interval,
        repo_dir=repo_dir,
        data_dir=data_dir,
        db_path=db_path,
        api_base_url=f"http://{host}:{port}",
    )

    # Mount filesystem access for UI (memory + config directories)
    _mount_filesystem_access(data_dir or Path.home() / ".cambium", repo_dir)

    # Mount static UI assets (production) — must be LAST (catch-all)
    ui_dist = Path(__file__).parent.parent.parent.parent / "ui" / "dist"
    if ui_dist.exists():
        from starlette.staticfiles import StaticFiles
        from starlette.responses import FileResponse

        # Serve static assets (JS, CSS, images) at /assets/
        app.mount("/assets", StaticFiles(directory=str(ui_dist / "assets")), name="ui-assets")

        # SPA fallback: any unmatched GET returns index.html for client-side routing
        index_html = ui_dist / "index.html"

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            # Don't intercept API routes — only serve static files and SPA fallback
            # for paths that don't match any registered API endpoints.
            static_path = ui_dist / path
            if static_path.is_file() and ".." not in path:
                return FileResponse(str(static_path))
            return FileResponse(str(index_html))

        log.info(f"Serving UI from {ui_dist}")

    uvicorn.run(app, host=host, port=port, log_level=log_level)


def _mount_filesystem_access(data_dir: Path, repo_dir: Path | None) -> None:
    """Mount read-only filesystem endpoints for the UI."""
    import os as _os
    from starlette.staticfiles import StaticFiles

    memory_dir = data_dir / "memory"
    config_dir = _resolve_config_dir(repo_dir or Path.cwd())

    if memory_dir.exists():
        app.mount("/memory", StaticFiles(directory=str(memory_dir)), name="memory")
    if config_dir.exists():
        app.mount("/config", StaticFiles(directory=str(config_dir)), name="config")

    roots = {"memory": memory_dir, "config": config_dir}

    # Max size for /fs/read — larger files return a size-exceeded error so the
    # UI can show a message rather than hanging on a huge blob.
    FS_READ_MAX_BYTES = 1_000_000  # 1 MB

    # File extensions we're willing to return as text. Anything else (images,
    # binaries) should be linked to the StaticFiles mount instead.
    FS_TEXT_EXTENSIONS = {
        ".md", ".markdown", ".txt", ".yaml", ".yml", ".json",
        ".py", ".ts", ".tsx", ".js", ".jsx", ".toml", ".ini",
        ".cfg", ".conf", ".sh", ".log", ".csv", ".xml", ".html",
        ".css", ".sql", "",
    }

    def _resolve_fs_target(root: str, path: str) -> Path:
        base = roots.get(root)
        if base is None:
            raise HTTPException(400, f"Unknown root: {root}. Use 'memory' or 'config'.")
        target = (base / path).resolve()
        if not str(target).startswith(str(base.resolve())):
            raise HTTPException(403, "Path traversal not allowed")
        if not target.exists():
            raise HTTPException(404, f"Path not found: {path}")
        return target

    @app.get("/fs/ls")
    def list_directory(root: str, path: str = ""):
        """List files in memory or config directory."""
        target = _resolve_fs_target(root, path)
        if not target.is_dir():
            raise HTTPException(400, f"Not a directory: {path}")

        entries = []
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else None,
                "modified": stat.st_mtime,
            })
        return {"entries": entries}

    @app.get("/fs/read")
    def read_file(root: str, path: str):
        """Return the text contents of a file under memory or config.

        Guards: size cap, extension allow-list, path traversal protection
        (inherited from `_resolve_fs_target`). Binary files are rejected with
        415 so the UI can fall back to a download link via the StaticFiles
        mount.
        """
        target = _resolve_fs_target(root, path)
        if not target.is_file():
            raise HTTPException(400, f"Not a file: {path}")

        stat = target.stat()
        if stat.st_size > FS_READ_MAX_BYTES:
            raise HTTPException(
                413,
                f"File too large ({stat.st_size} bytes); max {FS_READ_MAX_BYTES}",
            )

        ext = target.suffix.lower()
        if ext not in FS_TEXT_EXTENSIONS:
            raise HTTPException(415, f"Unsupported file type: {ext or '(no extension)'}")

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "File is not valid UTF-8 text")

        return {
            "content": content,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "extension": ext,
        }
