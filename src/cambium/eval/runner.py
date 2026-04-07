"""EvalRunner — orchestrates eval execution across staging environments."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from cambium.eval.assertions import check_assertion
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

    def __init__(self, repo_dir: Path, live: bool = True) -> None:
        self.repo_dir = repo_dir
        self.live = live

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
        """Poll until no pending messages and no running episodes."""
        # Give the system a moment to start processing
        time.sleep(3)

        settled_count = 0
        while time.monotonic() < deadline:
            health = ctx.health()
            pending = health.get("pending_messages", 0)
            episodes = ctx.episodes()
            running = [ep for ep in episodes if ep.get("status") == "running"]

            if pending == 0 and not running:
                settled_count += 1
                # Require 3 consecutive settled checks to avoid false positives
                if settled_count >= 3:
                    return
            else:
                settled_count = 0

            time.sleep(2)
        log.warning("Timed out waiting for cascade to settle")
