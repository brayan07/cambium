"""CLI entrypoint: python -m cambium."""

import argparse
import json
import sys

from cambium.cli.init import init_user_repo


def cmd_init(args: argparse.Namespace) -> None:
    path = init_user_repo()
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


def cmd_fire(args: argparse.Namespace) -> None:
    import urllib.request
    import urllib.error

    payload = {}
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            # Treat as a simple string payload
            payload = {"message": args.payload}

    body = json.dumps({
        "type": args.event_type,
        "payload": payload,
        "source": args.source,
    }).encode()

    url = f"http://{args.host}:{args.port}/events"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"Event enqueued: {result['type']} (id={result['id'][:8]})")
    except urllib.error.URLError as e:
        print(f"Error: Could not reach Cambium server at {url} — {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="cambium", description="Cambium — personal AI agent engine")
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Initialise ~/.cambium/ user repo")

    # server
    srv = sub.add_parser("server", help="Start the Cambium API server")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8350)
    srv.add_argument("--live", action="store_true", help="Enable real claude -p execution")
    srv.add_argument("--poll-interval", type=float, default=2.0, help="Consumer poll interval in seconds")
    srv.add_argument("-v", "--verbose", action="store_true")

    # fire
    fire = sub.add_parser("fire", help="Enqueue an event via the API")
    fire.add_argument("event_type", help="Event type (e.g. goal_created)")
    fire.add_argument("payload", nargs="?", default="{}", help="JSON payload or plain string")
    fire.add_argument("--source", default="cli")
    fire.add_argument("--host", default="127.0.0.1")
    fire.add_argument("--port", type=int, default=8350)

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "server":
        cmd_server(args)
    elif args.command == "fire":
        cmd_fire(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
