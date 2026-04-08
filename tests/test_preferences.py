"""Tests for Phase 3 preference learning infrastructure."""

from __future__ import annotations

from pathlib import Path

import yaml


DEFAULTS = Path(__file__).resolve().parent.parent / "defaults"
PROMPTS = DEFAULTS / "adapters" / "claude-code" / "prompts"
SKILL_DIR = DEFAULTS / "adapters" / "claude-code" / "skills" / "user-alignment"


class TestSessionSummarizerPreferenceSignals:
    """Session-summarizer prompt includes preference signal detection."""

    def test_preference_signal_format(self):
        """Prompt contains preference_signal thought format with required fields."""
        text = (PROMPTS / "session-summarizer.md").read_text()

        assert "preference_signal" in text
        assert "Preference Signal Detection" in text
        # Required payload fields
        for field in ("type", "signal", "source_session", "routine", "confidence"):
            assert f'"{field}"' in text or f"'{field}'" in text or f"{field}" in text

    def test_digest_format_includes_preference_signals_section(self):
        """Digest format template has a Preference Signals section."""
        text = (PROMPTS / "session-summarizer.md").read_text()
        assert "## Preference Signals" in text


class TestConsolidatorPreferenceManagement:
    """Memory consolidator has preference belief management."""

    def test_consolidator_has_preference_management(self):
        """Prompt contains preference belief management section."""
        text = (PROMPTS / "memory-consolidator.md").read_text()

        assert "Preference Belief Management" in text
        assert "knowledge/user/preferences/" in text
        assert "challenge protocol" in text.lower()

    def test_consolidator_scan_window(self):
        """Consolidator uses 'scan' window instead of 'hourly'."""
        text = (PROMPTS / "memory-consolidator.md").read_text()

        assert '#### window: "scan"' in text
        assert "last_scan" in text
        # Ensure old naming is gone
        assert '#### window: "hourly"' not in text
        assert "last_hourly_scan" not in text


class TestTimerCadence:
    """Timer config uses 15-minute scan cadence."""

    def test_timer_cadence_scan(self):
        """Consolidator timer runs every 15 minutes with window: scan."""
        config = yaml.safe_load((DEFAULTS / "timers.yaml").read_text())
        timers = {t["name"]: t for t in config["timers"]}

        assert "consolidator-scan" in timers
        assert "consolidator-hourly" not in timers

        scan = timers["consolidator-scan"]
        assert scan["schedule"] == "*/15 * * * *"
        assert scan["payload"]["window"] == "scan"


class TestPreferencesSkillReference:
    """User-alignment skill includes preferences reference."""

    def test_preferences_reference_exists(self):
        """references/preferences.md exists with confidence interpretation table."""
        ref = SKILL_DIR / "references" / "preferences.md"
        assert ref.exists()

        text = ref.read_text()
        assert "Confidence" in text
        assert "0.9-1.0" in text
        assert "0.7-0.8" in text

    def test_skill_routing_table_includes_preferences(self):
        """SKILL.md routing table has a preferences row."""
        text = (SKILL_DIR / "SKILL.md").read_text()
        assert "preferences.md" in text
