"""CLI entrypoint: python -m cambium."""

import argparse
import json
import sys


def cmd_init(args: argparse.Namespace) -> None:
    from cambium.cli.init import init_user_repo

    path = init_user_repo(github=args.github, repo_name=args.repo_name)
    print(f"Initialised Cambium user repo at {path}")


def cmd_server(args: argparse.Namespace) -> None:
    from pathlib import Path

    from cambium.server.app import run_server

    run_server(
        host=args.host,
        port=args.port,
        live=args.live,
        poll_interval=args.poll_interval,
        log_level="debug" if args.verbose else "info",
        repo_dir=Path(args.repo_dir) if args.repo_dir else None,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        db_path=args.db_path,
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


def cmd_eval(args: argparse.Namespace) -> None:
    import logging
    from pathlib import Path

    from cambium.eval.model import load_eval, load_config_override, merge_config_overrides
    from cambium.eval.runner import EvalRunner
    from cambium.eval.report import format_console, format_json, save_baseline, load_baseline
    from cambium.eval.compare import compare, improved_or_maintained, format_comparison

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    config_path = Path(args.config)
    config = load_eval(config_path)

    # Override trial count from CLI
    if args.trials is not None:
        config.trials = args.trials

    # Load extra config override from CLI flag
    extra_override = None
    if args.config_override:
        extra_override = load_config_override(Path(args.config_override))

    # Determine repo dir — default to the eval config's parent's parent
    # (assumes evals/ lives in the repo root or defaults/)
    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()

    runner = EvalRunner(repo_dir)
    result = runner.run(config, extra_override=extra_override)

    # Output results
    if args.output == "json":
        print(format_json(result))
    else:
        print(format_console(result))

    # Save baseline
    if args.save_baseline:
        save_baseline(result, Path(args.save_baseline))
        print(f"\nBaseline saved to {args.save_baseline}")

    # Compare against baseline
    if args.compare_baseline:
        baseline = load_baseline(Path(args.compare_baseline))
        report = compare(baseline, result)
        print(f"\n{format_comparison(report)}")
        if not improved_or_maintained(report):
            sys.exit(1)

    # Exit non-zero if overall pass rate is below threshold
    if result.overall_pass_rate < 1.0:
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
    srv.add_argument("--repo-dir", help="Directory with code and configs (default: cwd)")
    srv.add_argument("--data-dir", help="Directory for runtime state — DB, memory, sessions (default: ~/.cambium)")
    srv.add_argument("--db-path", help="Override database path (default: <data-dir>/data/cambium.db)")
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

    # eval
    eval_parser = sub.add_parser("eval", help="Run evaluations against a staging instance")
    eval_parser.add_argument("config", help="Path to eval YAML config")
    eval_parser.add_argument("--trials", type=int, help="Override trial count")
    eval_parser.add_argument("--config-override", help="Path to override YAML")
    eval_parser.add_argument("--compare-baseline", help="Path to baseline JSON for comparison")
    eval_parser.add_argument("--save-baseline", help="Save results as baseline JSON")
    eval_parser.add_argument("--output", choices=["text", "json"], default="text")
    eval_parser.add_argument("--repo-dir", help="Repository directory (default: cwd)")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "server":
        cmd_server(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "eval":
        cmd_eval(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
