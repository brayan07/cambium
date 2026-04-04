"""Tests for the SQLite queue adapter."""

import time

from cambium.models.event import Event
from cambium.queue.sqlite import SQLiteQueue


class TestSQLiteQueue:
    def _make_event(self, type: str = "test_event", source: str = "test") -> Event:
        return Event.create(type=type, payload={"key": "value"}, source=source)

    def test_enqueue_dequeue_round_trip(self):
        q = SQLiteQueue()
        ev = self._make_event()
        q.enqueue(ev)

        results = q.dequeue(["test_event"])
        assert len(results) == 1
        assert results[0].id == ev.id
        assert results[0].type == "test_event"
        assert results[0].payload == {"key": "value"}
        assert results[0].status == "in_flight"

    def test_fifo_order(self):
        q = SQLiteQueue()
        events = []
        for i in range(3):
            ev = self._make_event()
            ev.payload = {"order": i}
            q.enqueue(ev)
            events.append(ev)
            time.sleep(0.001)  # ensure distinct timestamps

        results = q.dequeue(["test_event"], limit=3)
        assert [r.payload["order"] for r in results] == [0, 1, 2]

    def test_type_filtering(self):
        q = SQLiteQueue()
        q.enqueue(self._make_event(type="alpha"))
        q.enqueue(self._make_event(type="beta"))
        q.enqueue(self._make_event(type="alpha"))

        results = q.dequeue(["alpha"], limit=10)
        assert len(results) == 2
        assert all(r.type == "alpha" for r in results)

    def test_dequeue_skips_in_flight(self):
        q = SQLiteQueue()
        ev = self._make_event()
        q.enqueue(ev)

        first = q.dequeue(["test_event"])
        assert len(first) == 1

        second = q.dequeue(["test_event"])
        assert len(second) == 0

    def test_ack(self):
        q = SQLiteQueue()
        ev = self._make_event()
        q.enqueue(ev)

        dequeued = q.dequeue(["test_event"])
        q.ack(dequeued[0].id)

        # Should not be dequeued again
        assert q.dequeue(["test_event"]) == []
        assert q.pending_count() == 0

    def test_nack_returns_to_pending(self):
        q = SQLiteQueue()
        ev = self._make_event()
        q.enqueue(ev)

        dequeued = q.dequeue(["test_event"])
        q.nack(dequeued[0].id)

        # Should be available again
        again = q.dequeue(["test_event"])
        assert len(again) == 1
        assert again[0].attempts == 1

    def test_nack_max_attempts_marks_failed(self):
        q = SQLiteQueue(max_attempts=2)
        ev = self._make_event()
        q.enqueue(ev)

        # First attempt
        d1 = q.dequeue(["test_event"])
        q.nack(d1[0].id)

        # Second attempt — should go to failed
        d2 = q.dequeue(["test_event"])
        q.nack(d2[0].id)

        # Should NOT be available
        assert q.dequeue(["test_event"]) == []
        assert q.pending_count() == 0

    def test_pending_count_all(self):
        q = SQLiteQueue()
        assert q.pending_count() == 0
        q.enqueue(self._make_event(type="a"))
        q.enqueue(self._make_event(type="b"))
        assert q.pending_count() == 2

    def test_pending_count_filtered(self):
        q = SQLiteQueue()
        q.enqueue(self._make_event(type="a"))
        q.enqueue(self._make_event(type="b"))
        q.enqueue(self._make_event(type="a"))
        assert q.pending_count(["a"]) == 2
        assert q.pending_count(["b"]) == 1
        assert q.pending_count(["c"]) == 0

    def test_dequeue_empty_types_returns_empty(self):
        q = SQLiteQueue()
        q.enqueue(self._make_event())
        assert q.dequeue([]) == []

    def test_dequeue_limit(self):
        q = SQLiteQueue()
        for _ in range(5):
            q.enqueue(self._make_event())
        results = q.dequeue(["test_event"], limit=2)
        assert len(results) == 2

    def test_concurrent_dequeue_safety(self):
        """Two dequeue calls on the same connection should not return the same event."""
        q = SQLiteQueue()
        ev = self._make_event()
        q.enqueue(ev)

        first = q.dequeue(["test_event"])
        second = q.dequeue(["test_event"])
        assert len(first) == 1
        assert len(second) == 0
