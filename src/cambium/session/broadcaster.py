"""Stream broadcaster — fans out OpenAI chunks to multiple SSE subscribers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator
from uuid import uuid4

log = logging.getLogger(__name__)


class StreamBroadcaster:
    """Fans out OpenAI chat.completion.chunk dicts to async subscribers.

    Buffers events so late joiners can catch up. Subscribers receive
    all buffered events followed by live events until done.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._subscribers: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        self._buffer: list[dict[str, Any]] = []
        self._done = False

    def publish(self, chunk: dict[str, Any]) -> None:
        """Publish a chunk to all subscribers. Thread-safe via put_nowait."""
        self._buffer.append(chunk)
        for q in self._subscribers.values():
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                log.warning(f"Subscriber queue full for session {self.session_id}")

    def close(self) -> None:
        """Signal all subscribers that the stream is done."""
        self._done = True
        for q in self._subscribers.values():
            try:
                q.put_nowait(None)  # sentinel
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to the stream. Yields buffered + live chunks."""
        sub_id = str(uuid4())
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1000)
        self._subscribers[sub_id] = q

        try:
            # Replay buffer for late joiners
            for chunk in self._buffer:
                yield chunk

            if self._done:
                return

            # Live events
            while True:
                chunk = await q.get()
                if chunk is None:  # sentinel = done
                    return
                yield chunk
        finally:
            self._subscribers.pop(sub_id, None)

    @property
    def is_done(self) -> bool:
        return self._done

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class BroadcasterRegistry:
    """Global registry of active broadcasters, keyed by session_id."""

    def __init__(self) -> None:
        self._broadcasters: dict[str, StreamBroadcaster] = {}

    def create(self, session_id: str) -> StreamBroadcaster:
        broadcaster = StreamBroadcaster(session_id)
        self._broadcasters[session_id] = broadcaster
        return broadcaster

    def get(self, session_id: str) -> StreamBroadcaster | None:
        return self._broadcasters.get(session_id)

    def remove(self, session_id: str) -> None:
        self._broadcasters.pop(session_id, None)

    def active_count(self) -> int:
        return len(self._broadcasters)
