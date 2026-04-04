"""Abstract queue adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cambium.models.event import Event


class QueueAdapter(ABC):
    """Abstract base class for event queue adapters."""

    @abstractmethod
    def enqueue(self, event: Event) -> None:
        """Add an event to the queue."""
        ...

    @abstractmethod
    def dequeue(self, event_types: list[str], limit: int = 1) -> list[Event]:
        """Claim up to `limit` pending events matching the given types."""
        ...

    @abstractmethod
    def ack(self, event_id: str) -> None:
        """Mark an event as successfully processed."""
        ...

    @abstractmethod
    def nack(self, event_id: str) -> None:
        """Return an event to the queue for retry."""
        ...

    @abstractmethod
    def pending_count(self, event_types: list[str] | None = None) -> int:
        """Count pending events, optionally filtered by type."""
        ...
