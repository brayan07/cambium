"""Tests for the ClickUp polling event source."""

import json
import time
from unittest.mock import patch, MagicMock

from cambium.queue.sqlite import SQLiteQueue
from cambium.sources.clickup_poller import ClickUpPoller


def _make_task(task_id: str, name: str, status: str, tags: list[str] | None = None) -> dict:
    """Helper to create a mock ClickUp task."""
    return {
        "id": task_id,
        "name": name,
        "status": {"status": status},
        "tags": [{"name": t} for t in (tags or [])],
        "list": {"name": "Test List"},
        "description": f"Description for {name}",
        "markdown_description": f"# {name}\n\nDescription for {name}",
    }


def _poller_config(**overrides) -> dict:
    config = {
        "team_id": "123",
        "assignee_id": "456",
        "api_token_env": "TEST_CLICKUP_TOKEN",
        "status_channel_map": {
            "backlog": "goals",
            "queued": "tasks",
        },
        "poll_intervals": {
            "backlog": 0,  # Always poll in tests
            "queued": 0,
        },
    }
    config.update(overrides)
    return config


def test_poller_emits_to_correct_channels():
    """Tasks in different statuses emit to the mapped channels."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {"TEST_CLICKUP_TOKEN": "test-token"}):
        poller = ClickUpPoller(_poller_config(), queue)

    tasks = [
        _make_task("t1", "Groom me", "backlog"),
        _make_task("t2", "Execute me", "queued", tags=["implementation"]),
    ]

    with patch.object(poller, "_fetch_tasks", return_value=tasks):
        count = poller.poll()

    assert count == 2

    # Check goals channel
    goals = queue.consume(["goals"], limit=10)
    assert len(goals) == 1
    assert goals[0].payload["task_id"] == "t1"
    assert goals[0].source == "clickup-poller"

    # Check tasks channel
    task_msgs = queue.consume(["tasks"], limit=10)
    assert len(task_msgs) == 1
    assert task_msgs[0].payload["task_id"] == "t2"
    assert task_msgs[0].payload["risk_level"] == "medium"  # default


def test_deduplication():
    """Same task shouldn't be emitted twice within TTL."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {"TEST_CLICKUP_TOKEN": "test-token"}):
        poller = ClickUpPoller(_poller_config(dedup_ttl=3600), queue)

    tasks = [_make_task("t1", "Task One", "queued")]

    with patch.object(poller, "_fetch_tasks", return_value=tasks):
        count1 = poller.poll()
        count2 = poller.poll()

    assert count1 == 1
    assert count2 == 0  # Deduped


def test_dedup_expires():
    """After TTL, the same task can be emitted again."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {"TEST_CLICKUP_TOKEN": "test-token"}):
        poller = ClickUpPoller(_poller_config(dedup_ttl=1), queue)

    tasks = [_make_task("t1", "Task One", "queued")]

    with patch.object(poller, "_fetch_tasks", return_value=tasks):
        count1 = poller.poll()

    # Expire the dedup entry
    for key in poller._emitted:
        poller._emitted[key] = time.time() - 2

    with patch.object(poller, "_fetch_tasks", return_value=tasks):
        count2 = poller.poll()

    assert count1 == 1
    assert count2 == 1


def test_poll_interval_respected():
    """Statuses with future poll times are skipped."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {"TEST_CLICKUP_TOKEN": "test-token"}):
        poller = ClickUpPoller(
            _poller_config(poll_intervals={"backlog": 9999, "queued": 0}),
            queue,
        )

    # Force backlog to have been polled recently
    poller._last_poll["backlog"] = time.time()

    # Mock returns only the queued task (simulating API filtering)
    queued_tasks = [_make_task("t2", "Execute me", "queued")]

    with patch.object(poller, "_fetch_tasks", return_value=queued_tasks) as mock_fetch:
        count = poller.poll()

    # Only queued should have been fetched (backlog interval not reached)
    assert count == 1
    # fetch_tasks should have been called with only ["queued"]
    mock_fetch.assert_called_once_with(["queued"])


def test_execution_payload_has_full_details():
    """Execution tasks include description, risk level, and iteration context."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {"TEST_CLICKUP_TOKEN": "test-token"}):
        poller = ClickUpPoller(_poller_config(), queue)

    tasks = [_make_task("t1", "Build feature", "queued", tags=["implementation", "high-risk"])]

    with patch.object(poller, "_fetch_tasks", return_value=tasks):
        with patch.object(poller, "_detect_iteration_context", return_value=None):
            poller.poll()

    msgs = queue.consume(["tasks"], limit=10)
    payload = msgs[0].payload
    assert payload["task_name"] == "Build feature"
    assert payload["risk_level"] == "high"
    assert "description" in payload
    assert "today" in payload


def test_no_token_returns_zero():
    """Without an API token, poll returns 0 without error."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {}, clear=True):
        poller = ClickUpPoller(_poller_config(), queue)

    assert poller.poll() == 0


def test_iteration_detection_in_payload():
    """When a PR exists in comments, iteration context is included."""
    queue = SQLiteQueue(":memory:")

    with patch.dict("os.environ", {"TEST_CLICKUP_TOKEN": "test-token"}):
        poller = ClickUpPoller(_poller_config(), queue)

    tasks = [_make_task("t1", "Fix bug", "queued")]
    iteration = {"pr_url": "https://github.com/org/repo/pull/42", "feedback": ["Needs tests"]}

    with patch.object(poller, "_fetch_tasks", return_value=tasks):
        with patch.object(poller, "_detect_iteration_context", return_value=iteration):
            poller.poll()

    msgs = queue.consume(["tasks"], limit=10)
    payload = msgs[0].payload
    assert payload["iteration"]["pr_url"] == "https://github.com/org/repo/pull/42"
    assert "Needs tests" in payload["iteration"]["feedback"]
