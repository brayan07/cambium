#!/usr/bin/env python3
"""Live cascade demo — sends a real goal through the memory pipeline.

Cascade:
  1. Send goal to 'external_events' channel
  2. Coordinator processes it (real Claude session) → creates work item
  3. sessions_completed fires automatically when coordinator finishes
  4. Session-summarizer reads transcript, writes digest to memory/sessions/
  5. Send heartbeat targeting memory-consolidator
  6. Memory-consolidator reads digests, updates knowledge/, commits

Usage:
    Terminal 1 (server):
      cd /Users/bjaramillo/PycharmProjects/cambium
      .venv/bin/python -m cambium server --live

    Terminal 2 (demo):
      cd /Users/bjaramillo/PycharmProjects/cambium
      .venv/bin/python scripts/live_cascade_demo.py

Prerequisites:
    - cambium init has been run (~/.cambium/ populated)
    - claude CLI on PATH and authenticated
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_URL = "http://127.0.0.1:8350"
MEMORY_DIR = Path.home() / ".cambium" / "memory"


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


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def show_memory_tree() -> None:
    result = subprocess.run(
        ["find", str(MEMORY_DIR), "-type", "f", "-not", "-path", "*/.git/*"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        for line in sorted(result.stdout.strip().split("\n")):
            rel = line.replace(str(MEMORY_DIR) + "/", "")
            print(f"  {rel}")
    else:
        print("  (empty)")


def show_git_log() -> None:
    result = subprocess.run(
        ["git", "log", "--oneline", "-10"],
        cwd=MEMORY_DIR, capture_output=True, text=True,
    )
    if result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")
    else:
        print("  (no commits)")


def time_range() -> tuple[str, str]:
    """Return ISO since/until for today."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=1)).isoformat()
    until = (now + timedelta(minutes=10)).isoformat()
    return since, until


def show_episodes() -> None:
    since, until = time_range()
    episodes = api("GET", f"/episodes?since={since}&until={until}")
    if isinstance(episodes, list) and episodes:
        print(f"Episodes ({len(episodes)}):")
        for ep in episodes:
            summary = ep.get("session_summary") or ""
            summary_str = f"\n    summary: {summary[:80]}" if summary else ""
            print(
                f"  [{ep.get('status', '?'):10s}] {ep.get('routine', '?'):25s} "
                f"session={ep.get('session_id', '?')[:8]}{summary_str}"
            )
    else:
        print("No episodes found.")


def show_events() -> None:
    since, until = time_range()
    events = api("GET", f"/events?since={since}&until={until}")
    if isinstance(events, list) and events:
        print(f"Channel events ({len(events)}):")
        for ev in events:
            print(f"  {ev.get('channel', '?'):25s} | {ev.get('timestamp', '?')[:19]}")
    else:
        print("No events found.")


def wait_for_digest(timeout: int = 300) -> Path | None:
    """Poll for a new session digest file in memory/sessions/."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest_dir = MEMORY_DIR / "sessions" / today
    start = time.time()

    # Count existing digests
    existing = set(digest_dir.glob("*.md")) if digest_dir.exists() else set()

    while time.time() - start < timeout:
        if digest_dir.exists():
            current = set(digest_dir.glob("*.md"))
            new = current - existing
            if new:
                return next(iter(new))
        elapsed = int(time.time() - start)
        print(f"  [{elapsed:3d}s] Waiting for session digest...    ", end="\r")
        time.sleep(5)
    print()
    return None


def wait_for_knowledge_change(timeout: int = 300) -> list[Path]:
    """Poll for new or modified knowledge files."""
    knowledge_dir = MEMORY_DIR / "knowledge"
    start = time.time()

    # Snapshot existing files and their mtimes
    def snapshot():
        files = {}
        for f in knowledge_dir.rglob("*.md"):
            if f.name != "_index.md":
                files[f] = f.stat().st_mtime
        return files

    existing = snapshot()

    while time.time() - start < timeout:
        current = snapshot()
        changed = []
        for path, mtime in current.items():
            if path not in existing or existing[path] < mtime:
                changed.append(path)
        if changed:
            return changed
        elapsed = int(time.time() - start)
        print(f"  [{elapsed:3d}s] Waiting for knowledge update...    ", end="\r")
        time.sleep(5)
    print()
    return []


def main():
    section("STEP 0: Verify server")

    health = api("GET", "/health")
    if not health or health.get("status") != "ok":
        print("ERROR: Cambium server is not running.")
        print("\nStart it first:\n")
        print("  cd /Users/bjaramillo/PycharmProjects/cambium")
        print("  .venv/bin/python -m cambium server --live\n")
        sys.exit(1)

    print(f"Health: {json.dumps(health, indent=2)}")
    status = api("GET", "/queue/status")
    print(f"Queue: {json.dumps(status, indent=2)}")

    # ─── Step 1: Initial state ───
    section("STEP 1: Initial memory state")
    print("Memory tree:")
    show_memory_tree()
    print("\nGit log:")
    show_git_log()

    # ─── Step 2: Send a goal ───
    section("STEP 2: Send goal to 'external_events'")

    goal = {
        "payload": {
            "goal": (
                "Research and summarize: What are the three most important "
                "principles of effective spaced repetition? Write a brief "
                "explanation (3-5 sentences per principle)."
            ),
            "source": "live_demo",
        }
    }

    resp = api("POST", "/channels/external_events/send", goal)
    print(f"Published: {json.dumps(resp, indent=2)}")
    print("\nThe coordinator will now process this goal.")
    print("(Real Claude session — typically 30-90 seconds)")

    # ─── Step 3: Wait for coordinator completion ───
    section("STEP 3: Waiting for coordinator session...")

    start = time.time()
    while time.time() - start < 180:
        since, until = time_range()
        episodes = api("GET", f"/episodes?since={since}&until={until}")
        if isinstance(episodes, list):
            completed = [e for e in episodes if e.get("status") == "completed"]
            if completed:
                print(f"\nCoordinator session completed!")
                show_episodes()
                break
        elapsed = int(time.time() - start)
        print(f"  [{elapsed:3d}s] Waiting for session to complete...    ", end="\r")
        time.sleep(5)
    else:
        print("\nWARNING: Timed out waiting for coordinator. Check server logs.")

    # ─── Step 4: Wait for session-summarizer ───
    section("STEP 4: Waiting for session-summarizer...")
    print("sessions_completed was emitted. Summarizer should write a digest.\n")

    digest = wait_for_digest(timeout=180)
    if digest:
        print(f"\nDigest written: {digest.relative_to(MEMORY_DIR)}")
        print(f"\n--- Digest contents ---")
        content = digest.read_text()
        print(content[:800])
        if len(content) > 800:
            print(f"  ... ({len(content)} chars total)")
    else:
        print("WARNING: No digest found. Summarizer may still be running.")
        print("Continuing anyway — consolidator can still demo on existing state.")

    print("\nCurrent episodes:")
    show_episodes()

    # ─── Step 5: Trigger memory-consolidator ───
    section("STEP 5: Trigger memory-consolidator via heartbeat")

    heartbeat = {
        "payload": {
            "window": "hourly",
            "target": "memory-consolidator",
        }
    }
    resp = api("POST", "/channels/heartbeat/send", heartbeat)
    print(f"Published heartbeat: {json.dumps(resp, indent=2)}")
    print("\nMemory-consolidator should read digests and update knowledge/")
    print("(Real Claude Opus session — may take 1-3 minutes)\n")

    changed = wait_for_knowledge_change(timeout=300)
    if changed:
        print(f"\nKnowledge files updated: {len(changed)}")
        for kf in changed:
            rel = kf.relative_to(MEMORY_DIR)
            print(f"\n--- {rel} ---")
            content = kf.read_text()
            print(content[:500])
            if len(content) > 500:
                print(f"  ... ({len(content)} chars total)")
    else:
        print("No knowledge updates detected.")
        print("Check server logs — consolidator may have found nothing to update.")

    # ─── Step 6: Final state ───
    section("STEP 6: Final memory state")
    print("Memory tree:")
    show_memory_tree()
    print("\nGit log:")
    show_git_log()

    section("STEP 7: Final episodic index")
    show_episodes()
    print()
    show_events()

    # ─── Done ───
    print("\n" + "=" * 60)
    print("  DEMO COMPLETE")
    print("=" * 60)
    print()
    print("Inspect the memory directory:")
    print(f"  ls -la {MEMORY_DIR}/sessions/")
    print(f"  ls -la {MEMORY_DIR}/knowledge/")
    print(f"  cd {MEMORY_DIR} && git log --oneline")
    print()


if __name__ == "__main__":
    main()
