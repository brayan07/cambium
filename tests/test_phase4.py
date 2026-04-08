"""Tests for Phase 4: Attention Budget + Risk Calibration.

Verify that coordinator and consolidator prompts contain the necessary
attention budget and risk calibration sections, and that skill references
and routing table are properly configured.
"""

from __future__ import annotations

from pathlib import Path


DEFAULTS = Path(__file__).resolve().parent.parent / "defaults"
PROMPTS = DEFAULTS / "adapters" / "claude-code" / "prompts"
SKILLS = DEFAULTS / "adapters" / "claude-code" / "skills"
REFS = SKILLS / "user-alignment" / "references"


class TestCoordinatorAttentionBudget:
    """Coordinator prompt includes attention budget monitoring."""

    def test_prompt_has_attention_monitoring(self):
        text = (PROMPTS / "coordinator.md").read_text()
        assert "attention-budget" in text
        assert "overload" in text.lower()
        assert "requests/summary" in text

    def test_prompt_has_risk_aware_routing(self):
        text = (PROMPTS / "coordinator.md").read_text()
        assert "risk calibration" in text.lower()
        assert "Risk-aware routing" in text


class TestConsolidatorWeeklyBelief:
    """Consolidator prompt includes weekly attention budget and risk calibration."""

    def test_has_attention_budget_section(self):
        text = (PROMPTS / "memory-consolidator.md").read_text()
        assert "Attention Budget Maintenance" in text
        assert "weekly" in text.lower()
        assert "attention-budget.md" in text

    def test_has_risk_calibration_section(self):
        text = (PROMPTS / "memory-consolidator.md").read_text()
        assert "Risk Calibration Belief Management" in text
        assert "promotion" in text.lower()
        assert "No, keep asking" in text


class TestBudgetReference:
    """Budget reference document exists and has required content."""

    def test_exists_with_confidence_table(self):
        text = (REFS / "budget.md").read_text()
        assert "Confidence" in text
        assert "Interpretation" in text
        assert "overload" in text.lower()

    def test_references_cambium_data_dir(self):
        text = (REFS / "budget.md").read_text()
        assert "$CAMBIUM_DATA_DIR" in text


class TestRiskReference:
    """Risk reference document exists and has required content."""

    def test_exists_with_promotion_flow(self):
        text = (REFS / "risk.md").read_text()
        assert "promotion" in text.lower()
        assert "No, keep asking" in text
        assert "demotion" in text.lower()

    def test_never_auto_promotes(self):
        """The safety invariant: system never silently increases autonomy."""
        text = (REFS / "risk.md").read_text()
        assert "never" in text.lower()
        assert "No, keep asking" in text
        # Default must be conservative
        assert "Default" in text

    def test_references_cambium_data_dir(self):
        text = (REFS / "risk.md").read_text()
        assert "$CAMBIUM_DATA_DIR" in text


class TestSkillRoutingTable:
    """SKILL.md routing table includes budget and risk rows."""

    def test_has_budget_row(self):
        text = (SKILLS / "user-alignment" / "SKILL.md").read_text()
        assert "budget.md" in text

    def test_has_risk_row(self):
        text = (SKILLS / "user-alignment" / "SKILL.md").read_text()
        assert "risk.md" in text
