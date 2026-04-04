"""Queue adapters for Cambium."""

from cambium.queue.base import QueueAdapter
from cambium.queue.sqlite import SQLiteQueue

__all__ = ["QueueAdapter", "SQLiteQueue"]
