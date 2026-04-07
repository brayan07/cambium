"""Pre-eval structural checks — instant, free, catch structural failures."""

from __future__ import annotations

import logging
import py_compile
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


@dataclass
class PreflightResult:
    """Result of a single preflight check."""

    name: str
    passed: bool
    detail: str = ""


def syntax_check(repo_dir: Path) -> PreflightResult:
    """Verify all .py files compile without syntax errors."""
    errors = []
    src_dir = repo_dir / "src"
    if not src_dir.exists():
        return PreflightResult(name="syntax", passed=True, detail="No src/ directory")

    for py_file in src_dir.rglob("*.py"):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))

    if errors:
        return PreflightResult(
            name="syntax", passed=False,
            detail=f"{len(errors)} syntax error(s):\n" + "\n".join(errors[:5]),
        )
    return PreflightResult(name="syntax", passed=True)


def yaml_validate(repo_dir: Path) -> PreflightResult:
    """Validate all YAML files parse without errors."""
    errors = []
    defaults_dir = repo_dir / "defaults"
    if not defaults_dir.exists():
        # Try legacy layout
        defaults_dir = repo_dir

    for yaml_file in defaults_dir.rglob("*.yaml"):
        try:
            with open(yaml_file) as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            errors.append(f"{yaml_file.relative_to(repo_dir)}: {e}")

    for yaml_file in defaults_dir.rglob("*.yml"):
        try:
            with open(yaml_file) as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            errors.append(f"{yaml_file.relative_to(repo_dir)}: {e}")

    if errors:
        return PreflightResult(
            name="yaml", passed=False,
            detail=f"{len(errors)} YAML error(s):\n" + "\n".join(errors[:5]),
        )
    return PreflightResult(name="yaml", passed=True)


def import_check(repo_dir: Path) -> PreflightResult:
    """Verify core Cambium imports succeed."""
    result = subprocess.run(
        [sys.executable, "-c",
         "from cambium.server.app import build_server; "
         "from cambium.eval.model import load_eval"],
        capture_output=True, cwd=str(repo_dir), timeout=30,
    )
    if result.returncode != 0:
        return PreflightResult(
            name="import", passed=False,
            detail=result.stderr.decode()[:500],
        )
    return PreflightResult(name="import", passed=True)


def pytest_check(repo_dir: Path, marker: str | None = None) -> PreflightResult:
    """Run the test suite (or a subset via marker)."""
    cmd = [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=short"]
    if marker:
        cmd.extend(["-m", marker])

    result = subprocess.run(
        cmd, capture_output=True, cwd=str(repo_dir), timeout=300,
    )
    output = result.stdout.decode()
    if result.returncode != 0:
        return PreflightResult(
            name="pytest", passed=False,
            detail=output[-500:] + "\n" + result.stderr.decode()[-200:],
        )
    return PreflightResult(name="pytest", passed=True, detail=output.split("\n")[-2])


def boot_check(repo_dir: Path) -> PreflightResult:
    """Start the server, verify /health, then kill it."""
    import json
    import socket
    import time
    import urllib.request
    import urllib.error
    import tempfile

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    data_dir = Path(tempfile.mkdtemp(prefix="cambium-boot-check-"))
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "cambium", "server",
                "--port", str(port),
                "--repo-dir", str(repo_dir),
                "--data-dir", str(data_dir),
                "--db-path", ":memory:",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(repo_dir),
        )

        # Wait for health
        deadline = time.monotonic() + 15
        healthy = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode()
                return PreflightResult(
                    name="boot", passed=False,
                    detail=f"Server exited with code {proc.returncode}: {stderr[:300]}",
                )
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read())
                    if data.get("status") == "ok":
                        healthy = True
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.3)

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        if not healthy:
            return PreflightResult(name="boot", passed=False, detail="Server did not become healthy in 15s")
        return PreflightResult(name="boot", passed=True)
    finally:
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)


def run_preflight(repo_dir: Path, skip_pytest: bool = False) -> list[PreflightResult]:
    """Run all preflight checks in order. Stops on first failure."""
    checks = [
        ("syntax", lambda: syntax_check(repo_dir)),
        ("yaml", lambda: yaml_validate(repo_dir)),
        ("import", lambda: import_check(repo_dir)),
    ]
    if not skip_pytest:
        checks.append(("pytest", lambda: pytest_check(repo_dir)))
    checks.append(("boot", lambda: boot_check(repo_dir)))

    results = []
    for name, check_fn in checks:
        log.info(f"Preflight: {name}...")
        result = check_fn()
        results.append(result)
        if not result.passed:
            log.error(f"Preflight FAILED: {name} — {result.detail[:200]}")
            break
        log.info(f"Preflight OK: {name}")
    return results
