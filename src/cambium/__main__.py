"""CLI entrypoint: python -m cambium."""

import argparse
import json
import sys


def cmd_init(args: argparse.Namespace) -> None:
    from cambium.cli.init import init_user_repo

    path = init_user_repo(github=args.github, repo_name=args.repo_name)
    print(f"Initialised Cambium user repo at {path}")


def cmd_server(args: argparse.Namespace) -> None:
    from cambium.server.app import run_server

    run_server(
        host=args.host,
        port=args.port,
        live=args.live,
        poll_interval=args.poll_interval,
        log_level="debug" if args.verbose else "info",
    )


def cmd_send(args: argparse.Namespace) -> None:
    import urllib.request
    import urllib.error

    payload = {}
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"message": args.payload}

    body = json.dumps({"payload": payload}).encode()

    url = f"http://{args.host}:{args.port}/channels/{args.channel}/send"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"Message sent to '{result['channel']}' (id={result['id'][:8]})")
    except urllib.error.URLError as e:
        print(f"Error: Could not reach Cambium server at {url} — {e}", file=sys.stderr)
        sys.exit(1)


def cmd_chat(args: argparse.Namespace) -> None:
    import uuid
    from pathlib import Path

    from cambium.adapters.base import AdapterInstanceRegistry
    from cambium.models.routine import RoutineRegistry

    user_dir = Path.home() / ".cambium"

    # Load routine
    routine_reg = RoutineRegistry(user_dir / "routines")

    routine = routine_reg.get(args.routine)
    if routine is None:
        print(f"Error: routine '{args.routine}' not found", file=sys.stderr)
        sys.exit(1)

    # Load adapter instance
    instance_reg = AdapterInstanceRegistry(user_dir / "adapters" / "claude-code" / "instances")

    instance = instance_reg.get(routine.adapter_instance)
    if instance is None:
        print(f"Error: adapter instance '{routine.adapter_instance}' not found", file=sys.stderr)
        sys.exit(1)

    # Resolve adapter type
    adapter_types = _build_adapter_types(user_dir)
    adapter = adapter_types.get(instance.adapter_type)
    if adapter is None:
        print(f"Error: adapter type '{instance.adapter_type}' not found", file=sys.stderr)
        sys.exit(1)

    session_id = str(uuid.uuid4())
    session_dir = user_dir / "data" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    print(f"Starting chat (routine: {args.routine}, adapter: {instance.adapter_type}, session: {session_id[:8]})")

    try:
        adapter.attach(instance, session_id, cwd=session_dir)
    except NotImplementedError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _build_adapter_types(user_dir):
    """Build the registry of adapter types from the user directory."""
    from cambium.adapters.claude_code import ClaudeCodeAdapter
    from cambium.mcp.file_registry import FileRegistry
    from cambium.models.skill import SkillRegistry

    skill_dirs = [user_dir / "adapters" / "claude-code" / "skills"]
    skill_registry = SkillRegistry(*[d for d in skill_dirs if d.exists()])

    mcp_registry = FileRegistry(user_dir / "mcp-servers.json")

    claude_adapter = ClaudeCodeAdapter(skill_registry, user_dir=user_dir, mcp_registry=mcp_registry)
    return {claude_adapter.name: claude_adapter}


def main() -> None:
    parser = argparse.ArgumentParser(prog="cambium", description="Cambium — personal AI agent engine")
    sub = parser.add_subparsers(dest="command")

    # init
    init_parser = sub.add_parser("init", help="Initialise ~/.cambium/ user repo")
    init_parser.add_argument("--github", action="store_true", help="Create private GitHub repo")
    init_parser.add_argument("--repo-name", default="cambium-config", help="GitHub repo name")

    # server
    srv = sub.add_parser("server", help="Start the Cambium API server")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8350)
    srv.add_argument("--live", action="store_true", help="Enable real claude -p execution")
    srv.add_argument("--poll-interval", type=float, default=2.0, help="Consumer poll interval in seconds")
    srv.add_argument("-v", "--verbose", action="store_true")

    # send
    send = sub.add_parser("send", help="Send a message to a channel via the API")
    send.add_argument("channel", help="Channel name (e.g. goals, tasks)")
    send.add_argument("payload", nargs="?", default="{}", help="JSON payload or plain string")
    send.add_argument("--host", default="127.0.0.1")
    send.add_argument("--port", type=int, default=8350)

    # chat
    chat = sub.add_parser("chat", help="Attach to a live session via Claude CLI")
    chat.add_argument("routine", help="Routine name (e.g. interactive)")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "server":
        cmd_server(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "chat":
        cmd_chat(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
