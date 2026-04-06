"""Tests for the timer system."""

from __future__ import annotations

from datetime import datetime, timezone

from cambium.queue.sqlite import SQLiteQueue
from cambium.timer.loop import TimerLoop
from cambium.timer.model import TimerConfig, load_timers


class TestTimerConfig:
    def test_load_from_yaml(self, tmp_path):
        config = tmp_path / "timers.yaml"
        config.write_text("""\
timers:
  - name: test-timer
    channel: heartbeat
    schedule: "*/5 * * * *"
    payload: { window: micro, target: sentry }
  - name: no-payload
    channel: heartbeat
    schedule: "0 * * * *"
""")
        timers = load_timers(config)
        assert len(timers) == 2
        assert timers[0].name == "test-timer"
        assert timers[0].channel == "heartbeat"
        assert timers[0].schedule == "*/5 * * * *"
        assert timers[0].payload == {"window": "micro", "target": "sentry"}
        assert timers[1].payload == {}

    def test_load_missing_file(self, tmp_path):
        timers = load_timers(tmp_path / "nonexistent.yaml")
        assert timers == []

    def test_load_empty_file(self, tmp_path):
        config = tmp_path / "timers.yaml"
        config.write_text("")
        timers = load_timers(config)
        assert timers == []


class TestTimerFiring:
    def _make_timer(self, schedule: str = "*/5 * * * *", name: str = "test") -> TimerConfig:
        return TimerConfig(name=name, channel="heartbeat", schedule=schedule, payload={"x": 1})

    def test_fires_on_matching_minute(self):
        queue = SQLiteQueue()
        timer = self._make_timer("*/5 * * * *")
        loop = TimerLoop([timer], queue)

        # 12:00 matches */5
        now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
        fired = loop.tick(now)
        assert fired == 1

        messages = queue.consume(["heartbeat"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload == {"x": 1}
        assert messages[0].source == "timer:test"

    def test_does_not_fire_on_non_matching_minute(self):
        queue = SQLiteQueue()
        timer = self._make_timer("0 * * * *")  # only at :00
        loop = TimerLoop([timer], queue)

        # 12:03 does not match "0 * * * *"
        now = datetime(2026, 4, 6, 12, 3, 0, tzinfo=timezone.utc)
        fired = loop.tick(now)
        assert fired == 0

    def test_fires_at_correct_minute(self):
        queue = SQLiteQueue()
        timer = self._make_timer("30 * * * *")  # at :30
        loop = TimerLoop([timer], queue)

        # :29 — no fire
        assert loop.tick(datetime(2026, 4, 6, 12, 29, 0, tzinfo=timezone.utc)) == 0
        # :30 — fire
        assert loop.tick(datetime(2026, 4, 6, 12, 30, 0, tzinfo=timezone.utc)) == 1
        # :31 — no fire
        assert loop.tick(datetime(2026, 4, 6, 12, 31, 0, tzinfo=timezone.utc)) == 0


class TestNoDoubleFire:
    def test_does_not_fire_twice_in_same_minute(self):
        queue = SQLiteQueue()
        timer = TimerConfig(name="t", channel="heartbeat", schedule="*/5 * * * *")
        loop = TimerLoop([timer], queue)

        now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
        assert loop.tick(now) == 1

        # Same minute, different second — should not fire again
        now2 = datetime(2026, 4, 6, 12, 0, 30, tzinfo=timezone.utc)
        assert loop.tick(now2) == 0

    def test_fires_again_in_next_matching_minute(self):
        queue = SQLiteQueue()
        timer = TimerConfig(name="t", channel="heartbeat", schedule="*/5 * * * *")
        loop = TimerLoop([timer], queue)

        t1 = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
        assert loop.tick(t1) == 1

        t2 = datetime(2026, 4, 6, 12, 5, 0, tzinfo=timezone.utc)
        assert loop.tick(t2) == 1


class TestMultipleTimers:
    def test_independent_timers(self):
        queue = SQLiteQueue()
        t1 = TimerConfig(name="every5", channel="heartbeat", schedule="*/5 * * * *", payload={"a": 1})
        t2 = TimerConfig(name="hourly", channel="heartbeat", schedule="0 * * * *", payload={"b": 2})
        loop = TimerLoop([t1, t2], queue)

        # At :00, both should fire (0 matches both */5 and "0")
        now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
        assert loop.tick(now) == 2

        # At :05, only every5 fires
        now2 = datetime(2026, 4, 6, 12, 5, 0, tzinfo=timezone.utc)
        assert loop.tick(now2) == 1


class TestCronParsing:
    def test_daily_at_6am(self):
        queue = SQLiteQueue()
        timer = TimerConfig(name="daily", channel="heartbeat", schedule="0 6 * * *")
        loop = TimerLoop([timer], queue)

        # 6:00 AM — matches
        assert loop.tick(datetime(2026, 4, 6, 6, 0, 0, tzinfo=timezone.utc)) == 1
        # 7:00 AM — does not match
        assert loop.tick(datetime(2026, 4, 6, 7, 0, 0, tzinfo=timezone.utc)) == 0

    def test_weekly_monday_6am(self):
        queue = SQLiteQueue()
        timer = TimerConfig(name="weekly", channel="heartbeat", schedule="0 6 * * 1")
        loop = TimerLoop([timer], queue)

        # Monday 2026-04-06 is a Monday, 6:00 AM
        assert loop.tick(datetime(2026, 4, 6, 6, 0, 0, tzinfo=timezone.utc)) == 1
        # Tuesday 2026-04-07, 6:00 AM — does not match
        assert loop.tick(datetime(2026, 4, 7, 6, 0, 0, tzinfo=timezone.utc)) == 0
