"""ClickUp polling source — watches task statuses and publishes queue events.

Replaces the n8n grooming/execution polling loops with a single poller that
maps ClickUp task statuses to Cambium channels.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
from datetime import date
from typing import Any

from cambium.models.message import Message
from cambium.queue.base import QueueAdapter
from cambium.sources.base import EventSource

log = logging.getLogger(__name__)

# ClickUp API base
_API_BASE = "https://api.clickup.com/api/v2"


class ClickUpPoller(EventSource):
    """Polls ClickUp for tasks and publishes events to queue channels.

    Configuration (via ``config`` dict):
        api_token_env: Environment variable holding the ClickUp API token.
        team_id: ClickUp workspace/team ID.
        assignee_id: User ID to filter tasks by (e.g., Marcus's ID).
        status_channel_map: Dict mapping ClickUp status → Cambium channel.
        poll_intervals: Dict mapping ClickUp status → poll interval in seconds.
        dedup_ttl: Seconds to remember emitted task IDs for dedup (default 3600).
        grooming_statuses: Statuses that go through the grooming/triage path.
        execution_statuses: Statuses that go through the execution path.
    """

    def __init__(self, config: dict[str, Any], queue: QueueAdapter) -> None:
        self.queue = queue
        self.team_id = config["team_id"]
        self.assignee_id = config["assignee_id"]

        token_env = config.get("api_token_env", "CLICKUP_API_TOKEN")
        self._api_token = os.environ.get(token_env, "")
        if not self._api_token:
            log.warning("ClickUp API token not set (env: %s)", token_env)

        # Status → channel mapping
        self.status_channel_map: dict[str, str] = config.get("status_channel_map", {
            "backlog": "goals",
            "needs grooming": "goals",
            "queued": "tasks",
        })

        # Per-status poll intervals (seconds)
        self.poll_intervals: dict[str, float] = config.get("poll_intervals", {
            "backlog": 1800,        # 30 min — grooming pace
            "needs grooming": 1800,
            "queued": 120,          # 2 min — execution pace
        })

        self.dedup_ttl = config.get("dedup_ttl", 3600)

        # Internal state
        self._last_poll: dict[str, float] = {}
        self._emitted: dict[str, float] = {}  # dedup_key → timestamp

    def poll(self) -> int:
        """Check ClickUp for tasks and emit events. Returns count of events emitted."""
        if not self._api_token:
            return 0

        now = time.time()
        total_emitted = 0

        # Group statuses by their poll interval to batch API calls
        ready_statuses: list[str] = []
        for status in self.status_channel_map:
            interval = self.poll_intervals.get(status, 120)
            last = self._last_poll.get(status, 0)
            if now - last >= interval:
                ready_statuses.append(status)
                self._last_poll[status] = now

        if not ready_statuses:
            return 0

        # Fetch tasks for all ready statuses in one API call
        tasks = self._fetch_tasks(ready_statuses)
        log.info(
            "Polled ClickUp: %d tasks in statuses %s",
            len(tasks), ready_statuses,
        )

        for task in tasks:
            task_id = task.get("id", "")
            task_status = task.get("status", {}).get("status", "").lower()
            channel = self.status_channel_map.get(task_status)
            if not channel:
                continue

            dedup_key = f"{task_id}:{channel}"
            if dedup_key in self._emitted and now - self._emitted[dedup_key] < self.dedup_ttl:
                continue

            payload = self._build_payload(task, channel)
            message = Message.create(
                channel=channel,
                payload=payload,
                source="clickup-poller",
            )
            self.queue.publish(message)
            self._emitted[dedup_key] = now
            total_emitted += 1
            log.info(
                "Emitted %s → '%s' (task: %s)",
                task_id, channel, task.get("name", "?")[:60],
            )

        # Cleanup old dedup entries
        self._cleanup_dedup(now)

        return total_emitted

    def _fetch_tasks(self, statuses: list[str]) -> list[dict]:
        """Fetch tasks from ClickUp matching the given statuses."""
        params = [
            ("include_closed", "false"),
            ("subtasks", "true"),
        ]
        for s in statuses:
            params.append(("statuses[]", s))
        params.append(("assignees[]", self.assignee_id))

        query = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params)
        url = f"{_API_BASE}/team/{self.team_id}/task?{query}"

        req = urllib.request.Request(url, headers={
            "Authorization": self._api_token,
            "Content-Type": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("tasks", [])
        except urllib.error.URLError as e:
            log.error("ClickUp API error: %s", e)
            return []
        except json.JSONDecodeError:
            log.error("ClickUp API returned invalid JSON")
            return []

    def _fetch_comments(self, task_id: str) -> list[dict]:
        """Fetch comments on a task (for iteration detection)."""
        url = f"{_API_BASE}/task/{task_id}/comment"
        req = urllib.request.Request(url, headers={
            "Authorization": self._api_token,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("comments", [])
        except (urllib.error.URLError, json.JSONDecodeError):
            return []

    def _detect_iteration_context(self, task_id: str) -> dict | None:
        """Check if a PR already exists for this task (iteration pass).

        Returns a dict with pr_url and feedback if this is an iteration,
        or None for a first pass.
        """
        comments = self._fetch_comments(task_id)
        if not comments:
            return None

        pr_url = None
        for c in comments:
            text = c.get("comment_text", "")
            if "github.com" in text and "/pull/" in text:
                match = re.search(r"https://github\.com/[\w-]+/[\w.-]+/pull/\d+", text)
                if match:
                    pr_url = match.group(0)
                    break

        if not pr_url:
            return None

        # Collect Brayan's feedback (user ID 198076710)
        brayan_comments = []
        for c in comments:
            poster = c.get("user", {}).get("id")
            if poster == 198076710:
                text = c.get("comment_text", "").strip()
                if text:
                    brayan_comments.append(text)

        if not brayan_comments:
            return None

        return {"pr_url": pr_url, "feedback": brayan_comments}

    def _extract_risk_level(self, task: dict) -> str:
        """Extract risk level from task tags."""
        for tag in task.get("tags", []):
            name = tag.get("name", "").lower()
            if name in ("low-risk", "low"):
                return "low"
            elif name in ("high-risk", "high"):
                return "high"
            elif name in ("medium-risk", "medium"):
                return "medium"
        return "medium"

    def _build_payload(self, task: dict, channel: str) -> dict:
        """Build the event payload for a task.

        For execution tasks (channel='tasks'), includes full task details
        and iteration context. For grooming tasks (channel='goals'),
        includes minimal info — the triage routine fetches details itself.
        """
        task_id = task.get("id", "")
        task_name = task.get("name", "Untitled")
        tags = [t.get("name", "") for t in task.get("tags", [])]

        if channel == "tasks":
            # Execution path — include full details for the execution routine
            description = (
                task.get("markdown_description")
                or task.get("description")
                or "(no description)"
            )
            risk_level = self._extract_risk_level(task)
            list_name = task.get("list", {}).get("name", "Unknown")

            payload: dict[str, Any] = {
                "task_id": task_id,
                "task_name": task_name,
                "list_name": list_name,
                "tags": tags,
                "risk_level": risk_level,
                "description": description,
                "today": date.today().isoformat(),
            }

            # Check for iteration context
            iteration = self._detect_iteration_context(task_id)
            if iteration:
                payload["iteration"] = iteration

            return payload

        else:
            # Grooming/triage path — minimal payload, agent fetches details via MCP
            return {
                "task_id": task_id,
                "task_name": task_name,
                "status": task.get("status", {}).get("status", ""),
                "tags": tags,
                "today": date.today().isoformat(),
            }

    def _cleanup_dedup(self, now: float) -> None:
        """Remove expired dedup entries."""
        expired = [k for k, t in self._emitted.items() if now - t > self.dedup_ttl]
        for k in expired:
            del self._emitted[k]
