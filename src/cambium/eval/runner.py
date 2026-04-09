"""EvalRunner — orchestrates eval execution across staging environments."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from cambium.eval.assertions import check_assertion
from cambium.eval.manifest import load_manifest
from cambium.eval.model import (
    EvalConfig,
    EvalResult,
    ScenarioResult,
    TrialResult,
    load_config_override,
    merge_config_overrides,
)
from cambium.eval.staging import StagingContext, StagingEnvironment

log = logging.getLogger(__name__)


class EvalRunner:
    """Runs eval scenarios against staging Cambium instances."""

    def __init__(
        self, repo_dir: Path, live: bool = True, enforce_manifest: bool = False,
    ) -> None:
        self.repo_dir = repo_dir
        self.live = live
        self.enforce_manifest = enforce_manifest

    def run(
        self,
        config: EvalConfig,
        extra_override: dict[str, Any] | None = None,
    ) -> EvalResult:
        """Run all scenarios with the configured number of trials."""
        # Merge config overrides: eval YAML base + CLI overlay
        effective_override = config.config_override
        if extra_override:
            effective_override = merge_config_overrides(effective_override, extra_override)

        # Validate overrides against tunable manifest
        if self.enforce_manifest and effective_override:
            from cambium.server.app import _resolve_config_dir
            config_dir = _resolve_config_dir(self.repo_dir)
            manifest = load_manifest(config_dir)
            violations = manifest.validate_override(effective_override)
            if violations:
                raise ValueError(
                    f"Config override violates tunable manifest:\n"
                    + "\n".join(f"  - {v}" for v in violations)
                )

        scenario_results = []
        for scenario in config.scenarios:
            log.info(f"Scenario: {scenario.name}")
            trial_results = []

            for trial_num in range(config.trials):
                log.info(f"  Trial {trial_num + 1}/{config.trials}")
                result = self._run_trial(
                    scenario=scenario,
                    config_override=effective_override or None,
                    timeout=config.timeout,
                )
                trial_results.append(result)
                status = "PASS" if result.passed else "FAIL"
                log.info(f"  Trial {trial_num + 1}: {status} ({result.duration:.1f}s)")

            scenario_results.append(ScenarioResult(
                name=scenario.name, trials=trial_results,
            ))

        return EvalResult(name=config.name, scenarios=scenario_results)

    def _run_trial(
        self,
        scenario,
        config_override: dict[str, Any] | None,
        timeout: int,
    ) -> TrialResult:
        """Execute a single trial of a scenario."""
        start = time.monotonic()
        try:
            with StagingEnvironment(self.repo_dir, config_override, live=self.live) as ctx:
                # Seed data files into the staging data dir
                if scenario.seed_data:
                    self._seed_data(ctx, scenario.seed_data)

                # Seed requests into the staging DB
                if scenario.seed_requests:
                    self._seed_requests(ctx, scenario.seed_requests)

                # Seed metric readings
                if scenario.seed_readings:
                    self._seed_readings(ctx, scenario.seed_readings)

                # Inject messages
                for injection in scenario.inject:
                    if injection.delay > 0:
                        time.sleep(injection.delay)
                    ctx.send(injection.channel, injection.payload)
                    log.debug(f"    Injected to {injection.channel}")

                # Wait for condition
                self._wait(ctx, scenario.wait, timeout)

                # Run assertions
                assertion_results = [
                    check_assertion(ctx, a) for a in scenario.assertions
                ]

                passed = all(ar.passed for ar in assertion_results)
                duration = time.monotonic() - start

                return TrialResult(
                    passed=passed,
                    assertion_results=assertion_results,
                    duration=duration,
                )
        except Exception as e:
            duration = time.monotonic() - start
            log.error(f"    Trial error: {e}")
            return TrialResult(
                passed=False,
                duration=duration,
                error=str(e),
            )

    def _seed_data(self, ctx: StagingContext, seed_files) -> None:
        """Write seed files into the staging data dir and git-commit them.

        Files are written into the memory subdirectory (already initialized as
        a git repo by MemoryService).  After writing, files are staged and
        committed so the consolidator and other routines can see them.
        """
        memory_dir = ctx.data_dir / "memory"
        for sf in seed_files:
            target = ctx.data_dir / sf.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sf.content)
            log.debug(f"    Seeded {sf.path}")

        # Git-commit seeded files in the memory repo
        if memory_dir.exists() and (memory_dir / ".git").exists():
            subprocess.run(
                ["git", "add", "."], cwd=memory_dir,
                capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Seed eval fixtures"],
                cwd=memory_dir, capture_output=True, check=True,
            )
            log.debug("    Committed seed data to memory repo")

    def _seed_requests(self, ctx: StagingContext, seed_requests) -> None:
        """Seed requests into the staging DB via the /requests/seed endpoint."""
        for sr in seed_requests:
            payload = {
                "type": sr.type,
                "summary": sr.summary,
                "detail": sr.detail,
                "session_id": sr.session_id,
                "created_by": sr.created_by,
            }
            if sr.options:
                payload["options"] = sr.options
            if sr.default:
                payload["default"] = sr.default
            if sr.timeout_hours:
                payload["timeout_hours"] = sr.timeout_hours
            ctx.post("/requests/seed", payload)
            log.debug(f"    Seeded request: {sr.summary}")

    def _seed_readings(self, ctx: StagingContext, seed_readings) -> None:
        """Seed metric readings into the staging DB via the /metrics/seed endpoint."""
        payload = [
            {
                "metric_name": sr.metric_name,
                "value": sr.value,
                "detail": sr.detail,
                "source": sr.source,
                **({"recorded_at": sr.recorded_at} if sr.recorded_at else {}),
            }
            for sr in seed_readings
        ]
        ctx.post("/metrics/seed", payload)
        log.debug(f"    Seeded {len(seed_readings)} metric reading(s)")

    def _wait(self, ctx: StagingContext, wait, timeout: int) -> None:
        """Wait for the specified condition."""
        deadline = time.monotonic() + timeout

        if wait.timeout_only:
            time.sleep(timeout)
            return

        if wait.routine_completed:
            self._wait_routine_completed(ctx, wait.routine_completed, deadline)
            return

        if wait.cascade_settled:
            self._wait_cascade_settled(ctx, deadline)
            return

    def _wait_routine_completed(
        self, ctx: StagingContext, routine: str, deadline: float,
    ) -> None:
        """Poll until a routine has a completed episode."""
        while time.monotonic() < deadline:
            episodes = ctx.episodes(routine=routine)
            completed = [ep for ep in episodes if ep.get("status") == "completed"]
            if completed:
                return
            time.sleep(2)
        log.warning(f"Timed out waiting for routine '{routine}' to complete")

    def _wait_cascade_settled(self, ctx: StagingContext, deadline: float) -> None:
        """Poll until no pending messages, no in-flight, and no running episodes.

        The consumer moves messages from 'pending' to 'in_flight' on consume,
        so we must check both to avoid declaring settled during inter-routine
        hand-offs (e.g., executor publishes to 'completions' but reviewer
        hasn't started yet).
        """
        # Give the system a moment to start processing
        time.sleep(5)

        settled_count = 0
        prev_episode_count = 0
        while time.monotonic() < deadline:
            health = ctx.health()
            pending = health.get("pending_messages", 0)
            in_flight = health.get("in_flight_messages", 0)
            episodes = ctx.episodes()
            running = [ep for ep in episodes if ep.get("status") == "running"]
            total_episodes = len(episodes)

            is_quiet = pending == 0 and in_flight == 0 and not running

            if is_quiet and total_episodes == prev_episode_count:
                settled_count += 1
                # Require 5 consecutive quiet checks (15s) to avoid false
                # positives during inter-routine hand-offs.
                if settled_count >= 5:
                    return
            else:
                settled_count = 0

            prev_episode_count = total_episodes
            time.sleep(3)
        log.warning("Timed out waiting for cascade to settle")
