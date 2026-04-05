"""Tests for the schedule event source."""

import time

from cambium.queue.sqlite import SQLiteQueue
from cambium.sources.schedule import ScheduleSource


def test_emits_on_first_poll():
    """First poll always emits (no previous timestamp)."""
    queue = SQLiteQueue(":memory:")
    source = ScheduleSource({"channel": "schedule", "interval": 60}, queue)

    count = source.poll()
    assert count == 1

    msgs = queue.consume(["schedule"], limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["trigger"] == "schedule"
    assert msgs[0].source == "schedule"
    assert "today" in msgs[0].payload
    assert "timestamp" in msgs[0].payload


def test_respects_interval():
    """Second poll within interval returns 0."""
    queue = SQLiteQueue(":memory:")
    source = ScheduleSource({"interval": 9999}, queue)

    count1 = source.poll()
    count2 = source.poll()

    assert count1 == 1
    assert count2 == 0


def test_emits_after_interval_expires():
    """After interval elapses, emits again."""
    queue = SQLiteQueue(":memory:")
    source = ScheduleSource({"interval": 1}, queue)

    count1 = source.poll()
    assert count1 == 1

    # Simulate time passing
    source._last_emit = time.time() - 2

    count2 = source.poll()
    assert count2 == 1

    # Should have 2 messages total in queue
    msgs = queue.consume(["schedule"], limit=10)
    assert len(msgs) == 2


def test_default_channel():
    """Defaults to 'schedule' channel."""
    queue = SQLiteQueue(":memory:")
    source = ScheduleSource({}, queue)

    source.poll()
    msgs = queue.consume(["schedule"], limit=10)
    assert len(msgs) == 1


def test_custom_channel():
    """Can emit to a custom channel."""
    queue = SQLiteQueue(":memory:")
    source = ScheduleSource({"channel": "custom-trigger"}, queue)

    source.poll()
    msgs = queue.consume(["custom-trigger"], limit=10)
    assert len(msgs) == 1


def test_payload_extras():
    """Extra fields are merged into the payload."""
    queue = SQLiteQueue(":memory:")
    source = ScheduleSource(
        {"payload_extras": {"routine_hint": "grooming"}},
        queue,
    )

    source.poll()
    msgs = queue.consume(["schedule"], limit=10)
    assert msgs[0].payload["routine_hint"] == "grooming"
    assert msgs[0].payload["trigger"] == "schedule"  # Still present
