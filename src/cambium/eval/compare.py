"""Baseline comparison — detect regressions and improvements."""

from __future__ import annotations

from dataclasses import dataclass

from cambium.eval.model import EvalResult


@dataclass
class ScenarioComparison:
    name: str
    baseline_pass_rate: float
    current_pass_rate: float

    @property
    def delta(self) -> float:
        return self.current_pass_rate - self.baseline_pass_rate

    @property
    def regressed(self) -> bool:
        # Allow small fluctuation (5%) before flagging regression
        return self.delta < -0.05

    @property
    def improved(self) -> bool:
        return self.delta > 0.05


@dataclass
class ComparisonReport:
    baseline_name: str
    current_name: str
    scenarios: list[ScenarioComparison]

    @property
    def any_regressed(self) -> bool:
        return any(s.regressed for s in self.scenarios)

    @property
    def any_improved(self) -> bool:
        return any(s.improved for s in self.scenarios)


def compare(baseline: EvalResult, current: EvalResult) -> ComparisonReport:
    """Compare current eval results against a baseline."""
    baseline_map = {s.name: s for s in baseline.scenarios}
    current_map = {s.name: s for s in current.scenarios}

    comparisons = []
    all_names = sorted(set(list(baseline_map.keys()) + list(current_map.keys())))

    for name in all_names:
        b_rate = baseline_map[name].pass_rate if name in baseline_map else 0.0
        c_rate = current_map[name].pass_rate if name in current_map else 0.0
        comparisons.append(ScenarioComparison(
            name=name,
            baseline_pass_rate=b_rate,
            current_pass_rate=c_rate,
        ))

    return ComparisonReport(
        baseline_name=baseline.name,
        current_name=current.name,
        scenarios=comparisons,
    )


def improved_or_maintained(report: ComparisonReport) -> bool:
    """Gate check: True if no scenario regressed."""
    return not report.any_regressed


def format_comparison(report: ComparisonReport) -> str:
    """Format comparison report for console output."""
    lines = [
        f"Comparison: {report.baseline_name} -> {report.current_name}",
        "=" * 60,
    ]

    for s in report.scenarios:
        if s.regressed:
            indicator = "REGRESSED"
        elif s.improved:
            indicator = "IMPROVED"
        else:
            indicator = "MAINTAINED"

        delta_str = f"{s.delta:+.0%}"
        lines.append(
            f"  {s.name}: {s.baseline_pass_rate:.0%} -> {s.current_pass_rate:.0%} "
            f"({delta_str}) [{indicator}]"
        )

    gate = "PASS" if improved_or_maintained(report) else "FAIL (regression detected)"
    lines.append(f"\nGate: {gate}")
    lines.append("=" * 60)
    return "\n".join(lines)
