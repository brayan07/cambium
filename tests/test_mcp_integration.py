#!/usr/bin/env python3
"""Live integration test: verify MCP servers are available in Claude sessions.

Registers a dummy MCP server (ping → pong), launches a real Claude session
via the adapter, and asks it to call the ping tool.

Usage:
    .venv/bin/python tests/test_mcp_integration.py
"""

import json
import sys
import tempfile
import uuid
from pathlib import Path

# Ensure the source is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cambium.adapters.base import AdapterInstance
from cambium.adapters.claude_code import ClaudeCodeAdapter
from cambium.mcp.file_registry import FileRegistry
from cambium.models.skill import SkillRegistry

DUMMY_SERVER_PATH = Path(__file__).parent / "dummy_mcp_server.py"
PYTHON = Path(__file__).parent.parent / ".venv" / "bin" / "python"


def main():
    # 1. Set up MCP registry with dummy server
    mcp_file = Path(tempfile.mktemp(suffix=".json"))
    mcp_file.write_text(json.dumps({
        "dummy-ping": {
            "command": str(PYTHON),
            "args": [str(DUMMY_SERVER_PATH)],
        }
    }))

    mcp_registry = FileRegistry(mcp_file)
    print(f"[setup] MCP registry: {list(mcp_registry.list_all().keys())}")

    # 2. Build adapter with empty skill registry
    skill_dir = Path(tempfile.mkdtemp()) / "skills"
    skill_dir.mkdir(parents=True)
    skill_registry = SkillRegistry(skill_dir)

    adapter = ClaudeCodeAdapter(
        skill_registry=skill_registry,
        mcp_registry=mcp_registry,
    )

    # 3. Create adapter instance with mcp_servers
    instance = AdapterInstance(
        name="mcp-test",
        adapter_type="claude-code",
        config={
            "model": "haiku",
            "mcp_servers": ["dummy-ping"],
            "timeout": 60,
        },
    )

    # 4. Collect events
    events = []

    def on_event(event):
        events.append(event)
        # Print text chunks as they arrive
        for choice in event.get("choices", []):
            delta = choice.get("delta", {})
            content = delta.get("content", "")
            if content:
                print(content, end="", flush=True)

    # 5. Send message asking to use the ping tool
    session_id = str(uuid.uuid4())
    print(f"\n[test] Sending message (session {session_id[:8]})...")
    print("[test] Asking Claude to call the dummy-ping MCP tool...\n")
    print("--- Claude output ---")

    result = adapter.send_message(
        instance=instance,
        user_message=(
            "You have an MCP tool called 'ping' from the 'dummy-ping' server. "
            "Please call it exactly once and tell me what it returned. "
            "Keep your response to one sentence."
        ),
        session_id=session_id,
        session_token="test-token",
        api_base_url="http://127.0.0.1:8350",
        live=True,
        on_event=on_event,
    )

    print("\n--- End output ---\n")

    # 6. Report results
    print(f"[result] success={result.success}")
    print(f"[result] duration={result.duration_seconds:.1f}s")
    if result.error:
        print(f"[result] error={result.error}")
    print(f"[result] output preview: {result.output[:200]}")

    # Check for tool_calls in events (indicates MCP tool was discovered)
    tool_calls = [
        e for e in events
        if any(
            "tool_calls" in choice.get("delta", {})
            for choice in e.get("choices", [])
        )
    ]
    print(f"\n[check] Tool call events: {len(tool_calls)}")

    if tool_calls:
        for tc in tool_calls:
            for choice in tc.get("choices", []):
                for call in choice.get("delta", {}).get("tool_calls", []):
                    fn = call.get("function", {})
                    print(f"  → {fn.get('name', '?')}({fn.get('arguments', '{}')})")

    # Verdict
    ping_called = any(
        call.get("function", {}).get("name", "") == "ping"
        for tc in tool_calls
        for choice in tc.get("choices", [])
        for call in choice.get("delta", {}).get("tool_calls", [])
    )

    if ping_called and result.success:
        print("\n✓ PASS — MCP server was discovered and ping tool was called")
        mcp_file.unlink(missing_ok=True)
        sys.exit(0)

    # Check if MCP was at least mentioned in output even without tool events
    if result.success and "pong" in result.output.lower():
        print("\n✓ PASS — pong found in output (tool call events may not have streamed)")
        mcp_file.unlink(missing_ok=True)
        sys.exit(0)

    print("\n✗ FAIL — ping tool was not called or session failed")
    mcp_file.unlink(missing_ok=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
