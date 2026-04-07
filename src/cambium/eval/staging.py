"""Staging environment — boots isolated Cambium instances for eval testing."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error
import json

import yaml

log = logging.getLogger(__name__)


@dataclass
class StagingContext:
    """Provides access to a running staging Cambium instance."""

    api_url: str
    data_dir: Path
    worktree_dir: Path | None
    process: subprocess.Popen
    port: int

    def get(self, path: str, params: dict | None = None) -> Any:
        """HTTP GET against the staging server."""
        url = f"{self.api_url}{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url = f"{url}?{query}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def post(self, path: str, payload: dict | None = None) -> Any:
        """HTTP POST against the staging server."""
        url = f"{self.api_url}{path}"
        body = json.dumps(payload or {}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def send(self, channel: str, payload: dict) -> dict:
        """Inject a message into a channel (unauthenticated)."""
        return self.post(f"/channels/{channel}/send", {"payload": payload})

    def health(self) -> dict:
        return self.get("/health")

    def episodes(self, **kwargs) -> list[dict]:
        # /episodes requires since and until — default to wide window
        if "since" not in kwargs:
            kwargs["since"] = "2000-01-01T00:00:00Z"
        if "until" not in kwargs:
            kwargs["until"] = datetime.now(timezone.utc).isoformat()
        return self.get("/episodes", params=kwargs)

    def events(self, **kwargs) -> list[dict]:
        return self.get("/events", params=kwargs)

    def work_items(self, **kwargs) -> list[dict]:
        resp = self.get("/work-items", params=kwargs)
        # API returns {items: [...], total, limit, truncated}
        if isinstance(resp, dict):
            return resp.get("items", [])
        return resp


def _find_free_port() -> int:
    """Bind to port 0 to get an OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _apply_yaml_override(file_path: Path, overrides: dict) -> None:
    """Deep-merge override keys into a YAML file."""
    if not file_path.exists():
        log.warning(f"Override target does not exist: {file_path}")
        return

    with open(file_path) as f:
        data = yaml.safe_load(f) or {}

    def _deep_merge(base: dict, overlay: dict) -> dict:
        merged = dict(base)
        for k, v in overlay.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = _deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged

    merged = _deep_merge(data, overrides)
    with open(file_path, "w") as f:
        yaml.safe_dump(merged, f, default_flow_style=False)


def _apply_markdown_override(file_path: Path, override: dict) -> None:
    """Apply a patch or full replacement to a markdown file."""
    if not file_path.exists():
        log.warning(f"Override target does not exist: {file_path}")
        return

    if "content" in override:
        # Full replacement
        file_path.write_text(override["content"])
    elif "append" in override:
        # Append to existing content
        current = file_path.read_text()
        file_path.write_text(current + "\n" + override["append"])
    elif "patch" in override:
        # Simple line-based patch: lines starting with + are added, - are removed
        current = file_path.read_text()
        patch_lines = override["patch"].strip().split("\n")
        additions = [line[1:] for line in patch_lines if line.startswith("+")]
        removals = {line[1:] for line in patch_lines if line.startswith("-")}

        result_lines = [l for l in current.split("\n") if l not in removals]
        result_lines.extend(additions)
        file_path.write_text("\n".join(result_lines))


def _apply_config_overrides(target_dir: Path, overrides: dict[str, Any]) -> None:
    """Apply config overrides to files in the target directory."""
    for file_rel, override_value in overrides.items():
        file_path = target_dir / file_rel
        if file_rel.endswith(".yaml") or file_rel.endswith(".yml"):
            _apply_yaml_override(file_path, override_value)
        elif file_rel.endswith(".md"):
            if isinstance(override_value, dict):
                _apply_markdown_override(file_path, override_value)
            else:
                # Treat as full content replacement
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(str(override_value))
        else:
            log.warning(f"Unsupported override file type: {file_rel}")


class StagingEnvironment:
    """Boots an isolated Cambium instance for eval testing.

    Uses git worktrees for config overrides (fast, shares object store)
    and a temp directory for runtime state (DB, memory, episodes).
    """

    def __init__(
        self,
        repo_dir: Path,
        config_override: dict[str, Any] | None = None,
        live: bool = True,
    ) -> None:
        self.repo_dir = repo_dir.resolve()
        self.config_override = config_override
        self.live = live
        self._ctx: StagingContext | None = None
        self._data_dir: Path | None = None
        self._worktree_dir: Path | None = None

    def __enter__(self) -> StagingContext:
        # 1. Create temp dir for runtime state
        self._data_dir = Path(tempfile.mkdtemp(prefix="cambium-eval-data-"))

        # 2. If config overrides, create a git worktree
        effective_repo = self.repo_dir
        if self.config_override:
            self._worktree_dir = Path(tempfile.mkdtemp(prefix="cambium-eval-repo-"))
            # Remove the temp dir — git worktree add needs a non-existing path
            shutil.rmtree(self._worktree_dir)
            try:
                subprocess.run(
                    ["git", "-C", str(self.repo_dir), "worktree", "add",
                     str(self._worktree_dir), "--detach"],
                    capture_output=True, check=True,
                )
            except subprocess.CalledProcessError as e:
                # Fallback: copy the repo if git worktree fails (not a git repo)
                log.warning(f"git worktree failed, falling back to copy: {e.stderr.decode()}")
                shutil.copytree(
                    self.repo_dir, self._worktree_dir,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db", ".venv", "node_modules"),
                )

            # Apply overrides in the worktree — resolve config dir for correct paths
            from cambium.server.app import _resolve_config_dir
            config_dir = _resolve_config_dir(self._worktree_dir)
            _apply_config_overrides(config_dir, self.config_override)
            effective_repo = self._worktree_dir

        # 3. Discover a free port
        port = _find_free_port()

        # 4. Boot server subprocess
        env = dict(os.environ)
        cmd = [
            sys.executable, "-m", "cambium", "server",
            "--port", str(port),
            "--repo-dir", str(effective_repo),
            "--data-dir", str(self._data_dir),
            "--db-path", ":memory:",
        ]
        if self.live:
            cmd.append("--live")
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(effective_repo),
        )

        # 5. Wait for /health with exponential backoff
        api_url = f"http://127.0.0.1:{port}"
        self._wait_for_health(api_url, proc, timeout=30)

        self._ctx = StagingContext(
            api_url=api_url,
            data_dir=self._data_dir,
            worktree_dir=self._worktree_dir,
            process=proc,
            port=port,
        )
        log.info(f"Staging server started on port {port} (pid={proc.pid})")
        return self._ctx

    def __exit__(self, *exc) -> None:
        try:
            self._kill_server()
        finally:
            try:
                self._cleanup_worktree()
            finally:
                self._cleanup_data_dir()

    def _wait_for_health(
        self, api_url: str, proc: subprocess.Popen, timeout: float = 30,
    ) -> None:
        """Poll /health until it responds or timeout."""
        deadline = time.monotonic() + timeout
        delay = 0.2
        while time.monotonic() < deadline:
            # Check process hasn't died
            if proc.poll() is not None:
                stdout = proc.stdout.read().decode() if proc.stdout else ""
                stderr = proc.stderr.read().decode() if proc.stderr else ""
                raise RuntimeError(
                    f"Staging server exited with code {proc.returncode}.\n"
                    f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}"
                )
            try:
                req = urllib.request.Request(f"{api_url}/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read())
                    if data.get("status") == "ok":
                        return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)

        # Timeout — kill the process and raise
        proc.kill()
        raise TimeoutError(
            f"Staging server did not become healthy within {timeout}s"
        )

    def _kill_server(self) -> None:
        """Gracefully stop the staging server."""
        if self._ctx is None or self._ctx.process.poll() is not None:
            return
        proc = self._ctx.process
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        log.info(f"Staging server stopped (pid={proc.pid})")

    def _cleanup_worktree(self) -> None:
        """Remove the git worktree if one was created."""
        if self._worktree_dir is None:
            return
        try:
            subprocess.run(
                ["git", "-C", str(self.repo_dir), "worktree", "remove",
                 str(self._worktree_dir), "--force"],
                capture_output=True, check=False,
            )
        except Exception:
            pass
        # Fallback: direct removal if git worktree remove didn't clean up
        if self._worktree_dir.exists():
            shutil.rmtree(self._worktree_dir, ignore_errors=True)

    def _cleanup_data_dir(self) -> None:
        """Remove the temp data directory."""
        if self._data_dir and self._data_dir.exists():
            shutil.rmtree(self._data_dir, ignore_errors=True)
