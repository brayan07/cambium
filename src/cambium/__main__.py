"""CLI entrypoint: python -m cambium."""

import sys
from cambium.cli.init import init_user_repo


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        path = init_user_repo()
        print(f"Initialised Cambium user repo at {path}")
    else:
        print("Usage: cambium init")


if __name__ == "__main__":
    main()
