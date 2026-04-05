"""Abstract base class for event sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cambium.queue.base import QueueAdapter


class EventSource(ABC):
    """An external integration that polls for state changes and publishes events.

    Sources run as background tasks alongside the consumer loop. Each call to
    ``poll()`` should check for new events and publish them to the queue.
    """

    @abstractmethod
    def poll(self) -> int:
        """Check for new events and publish to the queue.

        Returns the number of events published.
        """
        ...
