"""Cambium API server — the central coordination point for all Cambium operations."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cambium.models.event import Event
from cambium.models.routine import RoutineRegistry
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.runner.skill_runner import SkillRunner
from cambium.consumer.loop import ConsumerLoop

log = logging.getLogger(__name__)


# --- Pydantic request/response models ---


class EventCreate(BaseModel):
    """Request body for creating a new event."""

    type: str
    payload: dict = Field(default_factory=dict)
    source: str = "api"


class EventResponse(BaseModel):
    """Response body for an event."""

    id: str
    type: str
    payload: dict
    source: str
    timestamp: str
    status: str
    attempts: int


class QueueStatus(BaseModel):
    """Response body for queue status."""

    pending: int
    subscribed_event_types: list[str]


class HealthResponse(BaseModel):
    """Response body for health check."""

    status: str
    consumer_running: bool
    pending_events: int


# --- Server state ---


class CambiumServer:
    """Holds all server state and components."""

    def __init__(
        self,
        queue: SQLiteQueue,
        routine_registry: RoutineRegistry,
        skill_runner: SkillRunner,
        consumer: ConsumerLoop,
    ) -> None:
        self.queue = queue
        self.routine_registry = routine_registry
        self.skill_runner = skill_runner
        self.consumer = consumer
        self._consumer_task: asyncio.Task | None = None

    async def start_consumer(self) -> None:
        """Start the consumer loop as a background asyncio task."""
        self._consumer_task = asyncio.create_task(self._run_consumer())
        log.info("Consumer loop started")

    async def stop_consumer(self) -> None:
        """Stop the consumer loop."""
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
        """Run the consumer loop in async context, offloading blocking work to thread pool."""
        loop = asyncio.get_event_loop()
        while True:
            try:
                # Run tick in thread pool so it doesn't block the event loop
                results = await loop.run_in_executor(None, self.consumer.tick)
                for r in results:
                    status = "OK" if r.success else "FAIL"
                    log.info(f"Session result: {status} — {r.output[:100] if r.output else r.error}")
            except Exception:
                log.exception("Consumer tick error")
            await asyncio.sleep(self.consumer.poll_interval)


# --- Module-level state (set during lifespan) ---

_server: CambiumServer | None = None


def build_server(
    db_path: str | None = None,
    framework_dir: Path | None = None,
    user_dir: Path | None = None,
    live: bool = False,
    poll_interval: float = 2.0,
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

    # Skill registry — framework defaults + user overrides
    skill_dirs = [framework_dir / "defaults" / "skills"]
    if (user_dir / "skills").exists():
        skill_dirs.append(user_dir / "skills")
    skill_registry = SkillRegistry(*skill_dirs)

    # Routine registry
    routine_dirs = [framework_dir / "defaults" / "routines"]
    if (user_dir / "routines").exists():
        routine_dirs.append(user_dir / "routines")
    routine_registry = RoutineRegistry(*routine_dirs)

    # Runner and consumer
    skill_runner = SkillRunner(skill_registry)
    consumer = ConsumerLoop(
        queue=queue,
        routine_registry=routine_registry,
        skill_runner=skill_runner,
        poll_interval=poll_interval,
        live=live,
    )

    log.info(f"Skills: {skill_registry.names()}")
    log.info(f"Routines: {[r.name for r in routine_registry.all()]}")
    log.info(f"Queue DB: {db_path}")
    log.info(f"Live mode: {live}")

    return CambiumServer(
        queue=queue,
        routine_registry=routine_registry,
        skill_runner=skill_runner,
        consumer=consumer,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start consumer on startup, stop on shutdown."""
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
    version="0.1.0",
    lifespan=lifespan,
)


def _get_server() -> CambiumServer:
    if _server is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    return _server


# --- Routes ---


@app.post("/events", response_model=EventResponse, status_code=201)
def create_event(body: EventCreate):
    """Enqueue a new event."""
    server = _get_server()
    event = Event.create(type=body.type, payload=body.payload, source=body.source)
    server.queue.enqueue(event)
    log.info(f"Enqueued event: {event.type} (id={event.id[:8]})")
    return EventResponse(
        id=event.id,
        type=event.type,
        payload=event.payload,
        source=event.source,
        timestamp=event.timestamp.isoformat(),
        status="pending",
        attempts=0,
    )


@app.get("/queue/status", response_model=QueueStatus)
def queue_status():
    """Get queue status."""
    server = _get_server()
    return QueueStatus(
        pending=server.queue.pending_count(),
        subscribed_event_types=server.routine_registry.subscribed_event_types(),
    )


@app.post("/queue/{event_id}/ack")
def ack_event(event_id: str):
    """Acknowledge (complete) an event."""
    server = _get_server()
    server.queue.ack(event_id)
    return {"status": "acked", "event_id": event_id}


@app.post("/queue/{event_id}/nack")
def nack_event(event_id: str):
    """Negative-acknowledge (retry) an event."""
    server = _get_server()
    server.queue.nack(event_id)
    return {"status": "nacked", "event_id": event_id}


@app.get("/health", response_model=HealthResponse)
def health():
    """Health check."""
    server = _get_server()
    return HealthResponse(
        status="ok",
        consumer_running=server.consumer_running,
        pending_events=server.queue.pending_count(),
    )


# --- Entrypoint ---


def run_server(
    host: str = "127.0.0.1",
    port: int = 8350,
    live: bool = False,
    poll_interval: float = 2.0,
    log_level: str = "info",
) -> None:
    """Start the Cambium server."""
    global _server
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    _server = build_server(live=live, poll_interval=poll_interval)
    uvicorn.run(app, host=host, port=port, log_level=log_level)
