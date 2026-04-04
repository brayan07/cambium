"""Abstract queue adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cambium.models.message import Message


class QueueAdapter(ABC):
    """Abstract base class for channel-based message queues."""

    @abstractmethod
    def publish(self, message: Message) -> None:
        """Publish a message to its channel."""
        ...

    @abstractmethod
    def consume(self, channels: list[str], limit: int = 1) -> list[Message]:
        """Claim up to `limit` pending messages from the given channels."""
        ...

    @abstractmethod
    def ack(self, message_id: str) -> None:
        """Mark a message as successfully processed."""
        ...

    @abstractmethod
    def nack(self, message_id: str) -> None:
        """Return a message to the queue for retry."""
        ...

    @abstractmethod
    def pending_count(self, channels: list[str] | None = None) -> int:
        """Count pending messages, optionally filtered by channel."""
        ...
