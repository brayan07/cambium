"""Tests for the SQLite message queue."""

import threading

from cambium.models.message import Message
from cambium.queue.sqlite import SQLiteQueue


class TestSQLiteQueue:
    def test_publish_consume_round_trip(self):
        q = SQLiteQueue()
        msg = Message.create(channel="tasks", payload={"x": 1}, source="test")
        q.publish(msg)
        consumed = q.consume(["tasks"])
        assert len(consumed) == 1
        assert consumed[0].id == msg.id
        assert consumed[0].channel == "tasks"
        assert consumed[0].payload == {"x": 1}

    def test_fifo_order(self):
        q = SQLiteQueue()
        for i in range(3):
            q.publish(Message.create(channel="ch", payload={"i": i}, source="test"))
        msgs = q.consume(["ch"], limit=3)
        assert [m.payload["i"] for m in msgs] == [0, 1, 2]

    def test_channel_filtering(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="a", payload={}, source="test"))
        q.publish(Message.create(channel="b", payload={}, source="test"))
        msgs = q.consume(["a"])
        assert len(msgs) == 1
        assert msgs[0].channel == "a"

    def test_consume_skips_in_flight(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="ch", payload={}, source="test"))
        first = q.consume(["ch"])
        assert len(first) == 1
        second = q.consume(["ch"])
        assert len(second) == 0

    def test_ack(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="ch", payload={}, source="test"))
        msgs = q.consume(["ch"])
        q.ack(msgs[0].id)
        assert q.pending_count() == 0

    def test_nack_returns_to_pending(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="ch", payload={}, source="test"))
        msgs = q.consume(["ch"])
        q.nack(msgs[0].id)
        assert q.pending_count(["ch"]) == 1

    def test_nack_max_attempts_marks_failed(self):
        q = SQLiteQueue(max_attempts=2)
        q.publish(Message.create(channel="ch", payload={}, source="test"))
        for _ in range(2):
            msgs = q.consume(["ch"])
            q.nack(msgs[0].id)
        assert q.pending_count(["ch"]) == 0

    def test_pending_count_all(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="a", payload={}, source="test"))
        q.publish(Message.create(channel="b", payload={}, source="test"))
        assert q.pending_count() == 2

    def test_pending_count_filtered(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="a", payload={}, source="test"))
        q.publish(Message.create(channel="b", payload={}, source="test"))
        assert q.pending_count(["a"]) == 1

    def test_consume_empty_channels_returns_empty(self):
        q = SQLiteQueue()
        assert q.consume([]) == []

    def test_consume_limit(self):
        q = SQLiteQueue()
        for _ in range(5):
            q.publish(Message.create(channel="ch", payload={}, source="test"))
        msgs = q.consume(["ch"], limit=2)
        assert len(msgs) == 2

    def test_concurrent_consume_safety(self):
        q = SQLiteQueue()
        q.publish(Message.create(channel="ch", payload={}, source="test"))
        results = []

        def consume():
            results.append(q.consume(["ch"]))

        threads = [threading.Thread(target=consume) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        claimed = [r for r in results if len(r) > 0]
        assert len(claimed) == 1
