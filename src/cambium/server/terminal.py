"""WebSocket <-> PTY bridge for terminal sessions.

Spawns a pseudo-terminal running `cambium chat <routine>` and bridges
stdin/stdout over a WebSocket connection to the browser's xterm.js.

PTY lifecycle is decoupled from WebSocket lifecycle: PTYs persist after
WebSocket disconnects and are only cleaned up after an idle timeout or
natural exit. A background reader continuously buffers PTY output so
reconnecting clients can receive missed data.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])

IDLE_TIMEOUT = 15 * 60
OUTPUT_BUFFER_MAX = 100_000

_DB_TOUCH_INTERVAL = 120
_REAPER_INTERVAL = 60


@dataclass
class PtySession:
    """A PTY process linked to a Cambium session."""

    session_id: str
    pid: int
    fd: int
    last_activity: float = field(default_factory=time.time)
    last_db_touch: float = field(default_factory=time.time)
    output_buffer: deque = field(default_factory=lambda: deque(maxlen=OUTPUT_BUFFER_MAX))
    _connected_ws: WebSocket | None = field(default=None, repr=False)
    _reader_task: asyncio.Task | None = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def resize(self, rows: int, cols: int) -> None:
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def kill(self) -> None:
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    async def attach_ws(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connected_ws = ws

    async def detach_ws(self) -> None:
        async with self._lock:
            self._connected_ws = None

    async def send_to_ws(self, data: bytes) -> bool:
        async with self._lock:
            if self._connected_ws is None:
                return False
            try:
                await self._connected_ws.send_bytes(data)
                return True
            except Exception:
                self._connected_ws = None
                return False


_pty_sessions: dict[str, PtySession] = {}
_repo_dir: Path | None = None
_data_dir: Path | None = None
_session_store = None
_reaper_task: asyncio.Task | None = None


def configure(
    repo_dir: Path | None = None,
    data_dir: Path | None = None,
    session_store=None,
) -> None:
    global _repo_dir, _data_dir, _session_store
    _repo_dir = repo_dir
    _data_dir = data_dir
    _session_store = session_store


async def start_idle_reaper() -> None:
    global _reaper_task
    _reaper_task = asyncio.create_task(_idle_reaper_loop())
    log.info("PTY idle reaper started")


async def stop_idle_reaper() -> None:
    global _reaper_task
    if _reaper_task:
        _reaper_task.cancel()
        try:
            await _reaper_task
        except asyncio.CancelledError:
            pass
        _reaper_task = None
        log.info("PTY idle reaper stopped")


async def _idle_reaper_loop() -> None:
    while True:
        await asyncio.sleep(_REAPER_INTERVAL)
        now = time.time()
        to_reap = []
        for sid, session in list(_pty_sessions.items()):
            if not session.alive:
                to_reap.append((sid, "exited"))
            elif now - session.last_activity > IDLE_TIMEOUT:
                to_reap.append((sid, "idle"))
        for sid, reason in to_reap:
            session = _pty_sessions.get(sid)
            if session is None:
                continue
            log.info(f"PTY reaper: {reason} — {sid[:8]}")
            _destroy_session(session)


def _touch_session_db(session: PtySession) -> None:
    now = time.time()
    if now - session.last_db_touch < _DB_TOUCH_INTERVAL:
        return
    session.last_db_touch = now
    if _session_store is None:
        return
    try:
        _session_store.touch(session.session_id)
    except Exception:
        log.debug(f"Failed to touch session {session.session_id[:8]} in DB")


@router.websocket("/new")
async def terminal_new(
    ws: WebSocket,
    routine: str = Query(default="interlocutor"),
):
    await ws.accept()

    try:
        session = _spawn_pty(routine=routine)
    except Exception as e:
        log.error(f"Failed to spawn PTY: {e}")
        await ws.close(code=1011, reason=str(e))
        return

    _pty_sessions[session.session_id] = session
    _start_background_reader(session)
    log.info(f"PTY new: routine={routine} session={session.session_id[:8]}")

    _register_session(session.session_id, routine)

    await ws.send_text(json.dumps({
        "type": "session_init",
        "session_id": session.session_id,
        "routine": routine,
    }))

    try:
        ended_naturally = await _attach_and_bridge(ws, session)
    except WebSocketDisconnect:
        log.info(f"PTY WebSocket disconnected: {session.session_id[:8]}")
        ended_naturally = False
    finally:
        await session.detach_ws()

    if ended_naturally:
        _destroy_session(session)


@router.websocket("/{session_id}")
async def terminal_attach(
    ws: WebSocket,
    session_id: str,
    routine: str = Query(default="interlocutor"),
):
    await ws.accept()

    existing = _pty_sessions.get(session_id)
    if existing and existing.alive:
        log.info(f"PTY reattach: {session_id[:8]}")
        try:
            ended_naturally = await _attach_and_bridge(ws, existing)
        except WebSocketDisconnect:
            ended_naturally = False
        finally:
            await existing.detach_ws()
        if ended_naturally:
            _destroy_session(existing)
        return

    try:
        session = _spawn_pty(routine=routine, session_id=session_id, resume=True)
    except Exception as e:
        log.error(f"Failed to spawn PTY for resume: {e}")
        await ws.close(code=1011, reason=str(e))
        return

    _pty_sessions[session.session_id] = session
    _start_background_reader(session)
    _reactivate_session(session_id)
    log.info(f"PTY resume: session={session_id[:8]}")

    try:
        ended_naturally = await _attach_and_bridge(ws, session)
    except WebSocketDisconnect:
        log.info(f"PTY WebSocket disconnected: {session_id[:8]}")
        ended_naturally = False
    finally:
        await session.detach_ws()

    if ended_naturally:
        _destroy_session(session)


def _spawn_pty(
    routine: str = "interlocutor",
    session_id: str | None = None,
    resume: bool = False,
) -> PtySession:
    import sys
    import uuid

    if session_id is None:
        session_id = str(uuid.uuid4())

    cmd = [sys.executable, "-m", "cambium", "chat", routine, "--session-id", session_id]
    if resume:
        cmd.append("--resume")
    else:
        cmd.extend(["--message", "Session started from Cambium UI."])

    env = os.environ.copy()
    if _repo_dir:
        env["CAMBIUM_CONFIG_DIR"] = str(_repo_dir)
        cmd.extend(["--repo-dir", str(_repo_dir)])
    if _data_dir:
        env["CAMBIUM_DATA_DIR"] = str(_data_dir)
        cmd.extend(["--data-dir", str(_data_dir)])

    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(cmd[0], cmd, env)
    else:
        os.set_blocking(fd, False)
        return PtySession(
            session_id=session_id,
            pid=pid,
            fd=fd,
        )


def _start_background_reader(session: PtySession) -> None:
    session._reader_task = asyncio.create_task(_background_reader(session))


async def _background_reader(session: PtySession) -> None:
    """Read PTY output continuously; send to WS or buffer when disconnected."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            data = await loop.run_in_executor(None, _blocking_read, session.fd)
        except Exception:
            break
        if data is None:
            break
        if data:
            session.last_activity = time.time()
            sent = await session.send_to_ws(data)
            if not sent:
                session.output_buffer.extend(data)


async def _attach_and_bridge(ws: WebSocket, session: PtySession) -> bool:
    """Attach a WebSocket to an existing PTY session.

    Drains buffered output, then forwards WS input to PTY stdin.
    Returns True if the PTY process ended during this connection.
    """
    async with session._lock:
        if session.output_buffer:
            buffered = bytes(session.output_buffer)
            session.output_buffer.clear()
            try:
                await ws.send_bytes(buffered)
            except Exception:
                return False
        session._connected_ws = ws

    return await _ws_input_loop(ws, session)


async def _ws_input_loop(ws: WebSocket, session: PtySession) -> bool:
    """Read WebSocket messages and write to PTY stdin.

    Returns True if PTY exited naturally during this session.
    """
    async def write_pty() -> None:
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                break

            if msg["type"] == "websocket.disconnect":
                break

            if "bytes" in msg:
                data = msg["bytes"]
            elif "text" in msg:
                text = msg["text"]
                if text.startswith("{"):
                    try:
                        event = json.loads(text)
                        if event.get("type") == "resize":
                            session.resize(event["rows"], event["cols"])
                            continue
                        if event.get("type") == "keepalive":
                            session.last_activity = time.time()
                            _touch_session_db(session)
                            continue
                    except json.JSONDecodeError:
                        pass
                data = text.encode()
            else:
                continue

            try:
                os.write(session.fd, data)
            except OSError:
                break
            session.last_activity = time.time()
            _touch_session_db(session)

    async def watch_pty_exit() -> None:
        while session.alive:
            await asyncio.sleep(2)

    write_task = asyncio.create_task(write_pty())
    exit_task = asyncio.create_task(watch_pty_exit())

    done, pending = await asyncio.wait(
        [write_task, exit_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    return exit_task in done


def _blocking_read(fd: int) -> bytes | None:
    import select

    ready, _, _ = select.select([fd], [], [], 1.0)
    if ready:
        data = os.read(fd, 4096)
        if not data:
            return None
        return data
    return b""


def _register_session(session_id: str, routine: str) -> None:
    if _session_store is None:
        log.warning("No session store — PTY session won't appear in session list")
        return
    try:
        from datetime import datetime, timezone
        from cambium.session.model import Session as SessionModel, SessionOrigin, SessionStatus

        now = datetime.now(timezone.utc).isoformat()
        session = SessionModel(
            id=session_id,
            origin=SessionOrigin.USER,
            status=SessionStatus.ACTIVE,
            routine_name=routine,
            adapter_instance_name=routine,
            created_at=now,
            updated_at=now,
            metadata={"source": "terminal"},
        )
        _session_store.create_session(session)
        log.info(f"Registered PTY session {session_id[:8]} in session DB")
    except Exception as e:
        log.error(f"Failed to register PTY session: {e}")


def _reactivate_session(session_id: str) -> None:
    if _session_store is None:
        return
    try:
        from cambium.session.model import SessionStatus
        _session_store.update_status(session_id, SessionStatus.ACTIVE)
        log.info(f"Reactivated session {session_id[:8]}")
    except Exception as e:
        log.error(f"Failed to reactivate session: {e}")


def _complete_session(session_id: str) -> None:
    if _session_store is None:
        return
    try:
        from cambium.session.model import SessionStatus
        _session_store.update_status(session_id, SessionStatus.COMPLETED)
        log.info(f"Marked PTY session {session_id[:8]} as completed")
    except Exception as e:
        log.error(f"Failed to complete PTY session: {e}")


def _destroy_session(session: PtySession) -> None:
    """Kill PTY, remove from registry, mark completed in DB."""
    session.kill()
    _pty_sessions.pop(session.session_id, None)
    _complete_session(session.session_id)
    log.info(f"PTY session destroyed: {session.session_id[:8]}")
