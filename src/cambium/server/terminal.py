"""WebSocket <-> PTY bridge for terminal sessions.

Spawns a pseudo-terminal running `cambium chat <routine>` and bridges
stdin/stdout over a WebSocket connection to the browser's xterm.js.
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
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])

# 15-minute idle timeout (seconds)
IDLE_TIMEOUT = 15 * 60


@dataclass
class PtySession:
    """A PTY process linked to a Cambium session."""

    session_id: str
    pid: int
    fd: int  # PTY master file descriptor
    last_input: float = field(default_factory=time.time)

    def resize(self, rows: int, cols: int) -> None:
        """Send TIOCSWINSZ to the PTY."""
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def kill(self) -> None:
        """Terminate the PTY child process and close the fd."""
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
        """Check if the child process is still running."""
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False


# Registry of active PTY sessions
_pty_sessions: dict[str, PtySession] = {}

# Server configuration — set by configure()
_repo_dir: Path | None = None
_data_dir: Path | None = None


def configure(repo_dir: Path | None = None, data_dir: Path | None = None) -> None:
    """Set directory paths for spawning cambium chat commands."""
    global _repo_dir, _data_dir
    _repo_dir = repo_dir
    _data_dir = data_dir


@router.websocket("/new")
async def terminal_new(
    ws: WebSocket,
    routine: str = Query(default="interlocutor"),
):
    """Create a new session and open a terminal."""
    await ws.accept()

    try:
        session = _spawn_pty(routine=routine)
    except Exception as e:
        log.error(f"Failed to spawn PTY: {e}")
        await ws.close(code=1011, reason=str(e))
        return

    _pty_sessions[session.session_id] = session
    log.info(f"PTY new: routine={routine} session={session.session_id[:8]}")

    try:
        await _bridge(ws, session)
    except WebSocketDisconnect:
        log.info(f"PTY WebSocket disconnected: {session.session_id[:8]}")
    finally:
        _cleanup(session)


@router.websocket("/{session_id}")
async def terminal_attach(
    ws: WebSocket,
    session_id: str,
):
    """Reopen an existing session with --resume."""
    await ws.accept()

    # If a PTY is already alive for this session, reuse it
    existing = _pty_sessions.get(session_id)
    if existing and existing.alive:
        log.info(f"PTY reattach: {session_id[:8]}")
        try:
            await _bridge(ws, existing)
        except WebSocketDisconnect:
            pass
        return

    # Otherwise, spawn a new PTY that resumes the session
    try:
        session = _spawn_pty(session_id=session_id, resume=True)
    except Exception as e:
        log.error(f"Failed to spawn PTY for resume: {e}")
        await ws.close(code=1011, reason=str(e))
        return

    _pty_sessions[session.session_id] = session
    log.info(f"PTY resume: session={session_id[:8]}")

    try:
        await _bridge(ws, session)
    except WebSocketDisconnect:
        log.info(f"PTY WebSocket disconnected: {session_id[:8]}")
    finally:
        _cleanup(session)


def _spawn_pty(
    routine: str = "interlocutor",
    session_id: str | None = None,
    resume: bool = False,
) -> PtySession:
    """Fork a PTY running `cambium chat <routine>`.

    Replicates the adapter's attach() logic but in a child process
    instead of os.execvp (which would replace the server).
    """
    import sys
    import uuid

    if session_id is None:
        session_id = str(uuid.uuid4())

    # Build the cambium chat command — use the same Python that's running
    # the server so we don't depend on `cambium` being on PATH.
    cmd = [sys.executable, "-m", "cambium", "chat", routine]
    if resume:
        # TODO: cambium chat doesn't support --resume yet — for now,
        # we start a fresh session with the given ID. Resume support
        # requires extending the CLI.
        pass
    cmd.extend(["--message", "Session started from Cambium UI."])

    # Build environment with directory paths
    env = os.environ.copy()
    if _repo_dir:
        env["CAMBIUM_CONFIG_DIR"] = str(_repo_dir)
        cmd.extend(["--repo-dir", str(_repo_dir)])
    if _data_dir:
        env["CAMBIUM_DATA_DIR"] = str(_data_dir)
        cmd.extend(["--data-dir", str(_data_dir)])

    pid, fd = pty.fork()
    if pid == 0:
        # Child process — exec into cambium chat
        os.execvpe(cmd[0], cmd, env)
    else:
        # Parent — set non-blocking reads on the PTY master
        os.set_blocking(fd, False)
        return PtySession(
            session_id=session_id,
            pid=pid,
            fd=fd,
        )


async def _bridge(ws: WebSocket, session: PtySession) -> None:
    """Bidirectional bridge between WebSocket and PTY fd."""
    loop = asyncio.get_event_loop()

    async def read_pty() -> None:
        """PTY stdout -> WebSocket."""
        while True:
            try:
                data = await loop.run_in_executor(
                    None, _blocking_read, session.fd
                )
                if data is None:
                    # EOF — child process exited
                    break
                if data:
                    await ws.send_bytes(data)
                # Empty bytes (b"") means select() timed out — just loop
            except OSError:
                break
            except Exception:
                break

    async def write_pty() -> None:
        """WebSocket -> PTY stdin."""
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
                # Handle resize events: {"type":"resize","rows":N,"cols":N}
                if text.startswith("{"):
                    try:
                        event = json.loads(text)
                        if event.get("type") == "resize":
                            session.resize(event["rows"], event["cols"])
                            continue
                        if event.get("type") == "keepalive":
                            session.last_input = time.time()
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
            session.last_input = time.time()

    async def idle_watchdog() -> None:
        """Kill PTY after IDLE_TIMEOUT seconds of no input."""
        while True:
            await asyncio.sleep(60)
            if not session.alive:
                break
            if time.time() - session.last_input > IDLE_TIMEOUT:
                log.info(f"PTY idle timeout: {session.session_id[:8]}")
                session.kill()
                break

    tasks = [
        asyncio.create_task(read_pty()),
        asyncio.create_task(write_pty()),
        asyncio.create_task(idle_watchdog()),
    ]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _blocking_read(fd: int) -> bytes | None:
    """Blocking read from PTY fd.

    Uses select() with a short timeout so the executor thread doesn't
    block forever if the PTY goes idle.

    Returns:
        bytes: data read from PTY
        b"": select() timed out, no data available (not EOF)
        None: EOF — child process has exited
    """
    import select

    ready, _, _ = select.select([fd], [], [], 1.0)
    if ready:
        data = os.read(fd, 4096)
        if not data:
            return None  # EOF
        return data
    return b""


def _cleanup(session: PtySession) -> None:
    """Kill PTY and remove from registry."""
    session.kill()
    _pty_sessions.pop(session.session_id, None)
    log.info(f"PTY cleaned up: {session.session_id[:8]}")
