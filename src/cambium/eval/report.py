"""Eval result formatting — console and JSON output."""

from __future__ import annotations

import json
from pathlib import Path

from cambium.eval.model import EvalResult


def format_console(result: EvalResult) -> str:
    """Format eval results for console output."""
    lines = [f"Eval: {result.name}", "=" * 60]

    for scenario in result.scenarios:
        pass_rate = scenario.pass_rate
        status = "PASS" if pass_rate >= 1.0 else ("PARTIAL" if pass_rate > 0 else "FAIL")
        lines.append(f"\n  {scenario.name}: {status} ({pass_rate:.0%})")

        for i, trial in enumerate(scenario.trials):
            trial_status = "PASS" if trial.passed else "FAIL"
            lines.append(f"    Trial {i + 1}: {trial_status} ({trial.duration:.1f}s)")

            if trial.error:
                lines.append(f"      Error: {trial.error}")

            for ar in trial.assertion_results:
                check = "+" if ar.passed else "x"
                score_str = f" (score={ar.score:.2f})" if ar.score is not None else ""
                lines.append(f"      [{check}] {ar.assertion.type}{score_str}")
                if not ar.passed and ar.detail:
                    lines.append(f"          {ar.detail[:200]}")

    lines.append(f"\nOverall pass rate: {result.overall_pass_rate:.0%}")
    lines.append("=" * 60)
    return "\n".join(lines)


def format_json(result: EvalResult) -> str:
    """Format eval results as JSON for baseline comparison."""
    return json.dumps(_result_to_dict(result), indent=2)


def save_baseline(result: EvalResult, path: Path) -> None:
    """Save eval results as a JSON baseline file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_json(result))


def load_baseline(path: Path) -> EvalResult:
    """Load a baseline from a JSON file."""
    data = json.loads(path.read_text())
    return _dict_to_result(data)


def _result_to_dict(result: EvalResult) -> dict:
    return {
        "name": result.name,
        "overall_pass_rate": result.overall_pass_rate,
        "scenarios": [
            {
                "name": s.name,
                "pass_rate": s.pass_rate,
                "trials": [
                    {
                        "passed": t.passed,
                        "duration": t.duration,
                        "error": t.error,
                        "assertions": [
                            {
                                "type": ar.assertion.type,
                                "passed": ar.passed,
                                "score": ar.score,
                                "detail": ar.detail,
                            }
                            for ar in t.assertion_results
                        ],
                    }
                    for t in s.trials
                ],
            }
            for s in result.scenarios
        ],
    }


def _dict_to_result(data: dict) -> EvalResult:
    from cambium.eval.model import Assertion, AssertionResult, ScenarioResult, TrialResult

    scenarios = []
    for s_data in data.get("scenarios", []):
        trials = []
        for t_data in s_data.get("trials", []):
            assertion_results = [
                AssertionResult(
                    assertion=Assertion(type=a["type"]),
                    passed=a["passed"],
                    score=a.get("score"),
                    detail=a.get("detail", ""),
                )
                for a in t_data.get("assertions", [])
            ]
            trials.append(TrialResult(
                passed=t_data["passed"],
                duration=t_data.get("duration", 0),
                error=t_data.get("error"),
                assertion_results=assertion_results,
            ))
        scenarios.append(ScenarioResult(name=s_data["name"], trials=trials))

    return EvalResult(name=data["name"], scenarios=scenarios)
