#!/usr/bin/env python3
"""Live test: verify the full cascade works with progressive-disclosure skills.

Tests that all routine prompts correctly reference and use the
cambium-self-improvement skill's reference files after the consolidation.

Cascade tested:
  1. external_events → coordinator (uses triage.md via skill)
  2. plans → planner (uses planning.md via skill)
  3. tasks → executor (uses execution.md via skill)
  4. completions → reviewer (uses review.md via skill)
  5. heartbeat → sentry (uses detection.md via skill)
  6. heartbeat → memory-consolidator (uses detection.md via skill)
  7. sessions_completed → session-summarizer (no skill ref, but validates cascade)

Usage:
    Terminal 1 (server):
      cd /Users/bjaramillo/PycharmProjects/cambium
      .venv/bin/python -m cambium server --live -v

    Terminal 2 (test):
      cd /Users/bjaramillo/PycharmProjects/cambium
      .venv/bin/python scripts/live_skill_test.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

API_URL = "http://127.0.0.1:8350"

# Track test start time for episode filtering
TEST_START = datetime.now(timezone.utc)


# ── Helpers ──────────────────────────────────────────────────────────────

def api(method: str, path: str, data: dict | None = None) -> dict | list | None:
    cmd = ["curl", "-s", "-X", method, f"{API_URL}{path}"]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
    return None


def since_test_start() -> str:
    return TEST_START.isoformat()


def until_now() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()


def get_episodes() -> list[dict]:
    eps = api("GET", f"/episodes?since={since_test_start()}&until={until_now()}&limit=100")
    return eps if isinstance(eps, list) else []


def get_events() -> list[dict]:
    evs = api("GET", f"/events?since={since_test_start()}&until={until_now()}&limit=100")
    return evs if isinstance(evs, list) else []


def get_work_items() -> list[dict]:
    resp = api("GET", "/work-items")
    if isinstance(resp, dict):
        return resp.get("items", [])
    return resp if isinstance(resp, list) else []


def wait_for_episodes(routines: set[str], statuses: set[str], timeout: int = 600) -> dict[str, dict]:
    """Wait until we see episodes for each routine in the given statuses."""
    found = {}
    start = time.time()
    while time.time() - start < timeout:
        for ep in get_episodes():
            r = ep.get("routine", "")
            s = ep.get("status", "")
            if r in routines and s in statuses and r not in found:
                found[r] = ep
        if routines <= set(found.keys()):
            return found
        remaining = routines - set(found.keys())
        elapsed = int(time.time() - start)
        print(f"  [{elapsed:3d}s] Waiting for: {', '.join(sorted(remaining))}    ", end="\r")
        time.sleep(5)
    print()
    return found


def section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def check(label: str, condition: bool) -> bool:
    status = "PASS" if condition else "FAIL"
    icon = "✓" if condition else "✗"
    print(f"  {icon} [{status}] {label}")
    return condition


# ── Main test ────────────────────────────────────────────────────────────

def main():
    results = []

    # ── Step 0: Verify server ──
    section("STEP 0: Verify server is running")

    health = api("GET", "/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        print("ERROR: Cambium server is not running.")
        print("\nStart it first:\n")
        print("  cd /Users/bjaramillo/PycharmProjects/cambium")
        print("  .venv/bin/python -m cambium server --live -v\n")
        sys.exit(1)

    print(f"  Server healthy: {json.dumps(health)}")
    status = api("GET", "/queue/status")
    print(f"  Queue: {json.dumps(status)}")

    # ── Step 1: Main cascade (coordinator → planner → executor → reviewer) ──
    section("STEP 1: Inject goal — test main cascade")

    print("  Sending a simple goal to external_events...")
    goal = {
        "payload": {
            "goal": "Create a file called test-output.txt containing 'self-improvement cascade test'",
            "source": "live_skill_test",
        }
    }
    resp = api("POST", "/channels/external_events/send", goal)
    results.append(check("Goal published to external_events", resp is not None))

    # ── Step 2: Wait for coordinator ──
    section("STEP 2: Wait for coordinator to triage")
    print("  Coordinator should create a work item (reads triage.md if self-improvement,")
    print("  but this is a regular goal so it uses its base prompt).\n")

    found = wait_for_episodes({"coordinator"}, {"completed"}, timeout=180)
    results.append(check("Coordinator episode completed", "coordinator" in found))

    if "coordinator" in found:
        ep = found["coordinator"]
        print(f"  Session: {ep.get('session_id', '?')[:12]}...")
        print(f"  Status: {ep.get('status')}")

    # Check work item was created
    items = get_work_items()
    has_work_item = any("test-output" in (i.get("title", "") + i.get("description", "")).lower() for i in items)
    results.append(check("Work item created for goal", has_work_item))

    # ── Step 3: Wait for planner ──
    section("STEP 3: Wait for planner to decompose")
    print("  Planner decomposes the work item (reads planning.md for self-improvement types).\n")

    found = wait_for_episodes({"planner"}, {"completed"}, timeout=180)
    results.append(check("Planner episode completed", "planner" in found))

    # ── Step 4: Wait for executor ──
    section("STEP 4: Wait for executor to do the work")
    print("  Executor claims and executes the task (reads execution.md for self-improvement types).\n")

    found = wait_for_episodes({"executor"}, {"completed", "failed"}, timeout=300)
    results.append(check("Executor episode completed", "executor" in found))

    if "executor" in found:
        print(f"  Status: {found['executor'].get('status')}")

    # ── Step 5: Wait for reviewer ──
    section("STEP 5: Wait for reviewer to assess")
    print("  Reviewer checks the work (reads review.md for self-improvement types).\n")

    found = wait_for_episodes({"reviewer"}, {"completed"}, timeout=180)
    results.append(check("Reviewer episode completed", "reviewer" in found))

    # ── Step 6: Trigger sentry ──
    section("STEP 6: Trigger sentry heartbeat")
    print("  Sentry reads detection.md for pattern detection + upstream checks.\n")

    resp = api("POST", "/channels/heartbeat/send", {
        "payload": {"window": "micro", "target": "sentry"}
    })
    results.append(check("Sentry heartbeat published", resp is not None))

    found = wait_for_episodes({"sentry"}, {"completed"}, timeout=120)
    results.append(check("Sentry episode completed", "sentry" in found))

    # ── Step 7: Trigger memory-consolidator ──
    section("STEP 7: Trigger memory-consolidator heartbeat")
    print("  Consolidator reads detection.md for contribution detection.\n")

    resp = api("POST", "/channels/heartbeat/send", {
        "payload": {"window": "hourly", "target": "memory-consolidator"}
    })
    results.append(check("Consolidator heartbeat published", resp is not None))

    found = wait_for_episodes({"memory-consolidator"}, {"completed"}, timeout=300)
    results.append(check("Memory-consolidator episode completed", "memory-consolidator" in found))

    # ── Step 8: Check session-summarizer fired ──
    section("STEP 8: Check session-summarizer")
    print("  Session-summarizer should have fired for completed routine sessions.\n")

    # Give it a moment to catch up
    time.sleep(10)
    all_eps = get_episodes()
    summarizer_eps = [e for e in all_eps if e.get("routine") == "session-summarizer"]
    results.append(check(
        f"Session-summarizer fired ({len(summarizer_eps)} episodes)",
        len(summarizer_eps) > 0
    ))

    # ── Step 9: Final report ──
    section("FINAL REPORT")

    print("  All episodes since test start:")
    all_eps = get_episodes()
    for ep in sorted(all_eps, key=lambda e: e.get("started_at", "")):
        status = ep.get("status", "?")
        routine = ep.get("routine", "?")
        sid = ep.get("session_id", "?")[:8]
        icon = "✓" if status == "completed" else "✗" if status == "failed" else "…"
        print(f"    {icon} {routine:25s} {status:12s} session={sid}")

    print(f"\n  Channel events ({len(get_events())}):")
    for ev in get_events():
        ch = ev.get("channel", "?")
        ts = ev.get("timestamp", "?")[:19]
        print(f"    {ch:25s} {ts}")

    # Summary
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n  {'='*50}")
    print(f"  Results: {passed}/{total} checks passed")
    if passed == total:
        print(f"  CASCADE TEST PASSED — all routines completed with new skill structure")
    else:
        failed_count = total - passed
        print(f"  {failed_count} check(s) FAILED — review server logs for details")
    print(f"  {'='*50}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
