"""Integration tests for Phase 3 preference learning plumbing.

Smoke tests A: verify timer routing, prompt assembly, and skill resolution
work correctly with the new preference learning infrastructure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from unittest.mock import MagicMock, patch

from cambium.adapters.claude_code import ClaudeCodeAdapter
from cambium.adapters.base import AdapterInstance
from cambium.models.skill import SkillRegistry
from cambium.queue.sqlite import SQLiteQueue
from cambium.timer.loop import TimerLoop
from cambium.timer.model import load_timers


DEFAULTS = Path(__file__).resolve().parent.parent / "defaults"
PROMPTS = DEFAULTS / "adapters" / "claude-code" / "prompts"


# --- A1: Timer routing ---


class TestScanTimerRouting:
    """The consolidator-scan timer fires every 15 minutes with window: scan."""

    def test_loads_from_defaults_timers_yaml(self):
        """defaults/timers.yaml loads the consolidator-scan timer correctly."""
        timers = load_timers(DEFAULTS / "timers.yaml")
        by_name = {t.name: t for t in timers}

        assert "consolidator-scan" in by_name
        assert "consolidator-hourly" not in by_name

        scan = by_name["consolidator-scan"]
        assert scan.channel == "heartbeat"
        assert scan.schedule == "*/15 * * * *"
        assert scan.payload == {"window": "scan", "target": "memory-consolidator"}

    def test_fires_every_15_minutes(self):
        """Timer fires at :00, :15, :30, :45 but not at :05."""
        timers = load_timers(DEFAULTS / "timers.yaml")
        scan = [t for t in timers if t.name == "consolidator-scan"][0]

        queue = SQLiteQueue()
        loop = TimerLoop([scan], queue)

        # Should fire at :00
        assert loop.tick(datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)) == 1
        # Should NOT fire at :05
        assert loop.tick(datetime(2026, 4, 8, 12, 5, 0, tzinfo=timezone.utc)) == 0
        # Should fire at :15
        assert loop.tick(datetime(2026, 4, 8, 12, 15, 0, tzinfo=timezone.utc)) == 1
        # Should fire at :30
        assert loop.tick(datetime(2026, 4, 8, 12, 30, 0, tzinfo=timezone.utc)) == 1
        # Should fire at :45
        assert loop.tick(datetime(2026, 4, 8, 12, 45, 0, tzinfo=timezone.utc)) == 1

    def test_message_has_correct_target(self):
        """Published heartbeat message targets memory-consolidator."""
        timers = load_timers(DEFAULTS / "timers.yaml")
        scan = [t for t in timers if t.name == "consolidator-scan"][0]

        queue = SQLiteQueue()
        loop = TimerLoop([scan], queue)
        loop.tick(datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc))

        messages = queue.consume(["heartbeat"], limit=10)
        assert len(messages) == 1
        assert messages[0].payload["target"] == "memory-consolidator"
        assert messages[0].payload["window"] == "scan"
        assert messages[0].source == "timer:consolidator-scan"


# --- A2: Prompt assembly ---


class TestPromptAssembly:
    """System prompt for memory-consolidator includes preference learning sections."""

    def test_system_prompt_loads_with_preference_sections(self):
        """The consolidator prompt includes scan window and preference belief management."""
        skill_registry = SkillRegistry()
        adapter = ClaudeCodeAdapter(skill_registry, user_dir=DEFAULTS.parent)

        instance = AdapterInstance(
            name="memory-consolidator",
            adapter_type="claude-code",
            config={
                "model": "opus",
                "system_prompt_path": "defaults/adapters/claude-code/prompts/memory-consolidator.md",
                "skills": [],
            },
        )

        prompt = adapter._load_system_prompt(instance.config)

        # Scan window (renamed from hourly)
        assert 'window: "scan"' in prompt
        assert "last_scan" in prompt
        assert "last_hourly_scan" not in prompt

        # Preference belief management
        assert "Preference Belief Management" in prompt
        assert "knowledge/user/preferences/" in prompt
        assert "Challenge protocol" in prompt

    def test_prompts_use_cambium_data_dir(self):
        """Prompts reference $CAMBIUM_DATA_DIR, not $HOME/.cambium."""
        for prompt_name in ["memory-consolidator.md", "session-summarizer.md"]:
            text = (PROMPTS / prompt_name).read_text()
            assert "$CAMBIUM_DATA_DIR/memory" in text, f"{prompt_name} missing $CAMBIUM_DATA_DIR"
            assert "$HOME/.cambium/memory" not in text, f"{prompt_name} still uses $HOME/.cambium"

    def test_session_summarizer_prompt_has_preference_signals(self):
        """The session-summarizer prompt includes preference signal detection."""
        skill_registry = SkillRegistry()
        adapter = ClaudeCodeAdapter(skill_registry, user_dir=DEFAULTS.parent)

        instance = AdapterInstance(
            name="session-summarizer",
            adapter_type="claude-code",
            config={
                "model": "opus",
                "system_prompt_path": "defaults/adapters/claude-code/prompts/session-summarizer.md",
                "skills": [],
            },
        )

        prompt = adapter._load_system_prompt(instance.config)

        assert "Preference Signal Detection" in prompt
        assert "preference_signal" in prompt
        assert "## Preference Signals" in prompt


# --- A3: Skill resolution ---


class TestSkillResolution:
    """User-alignment skill loads correctly and includes preferences reference."""

    def test_skill_registry_loads_user_alignment(self):
        """SkillRegistry finds user-alignment skill with SKILL.md."""
        skill_dir = DEFAULTS / "adapters" / "claude-code" / "skills"
        registry = SkillRegistry(skill_dir)

        skill = registry.get("user-alignment")
        assert skill is not None
        assert skill.name == "user-alignment"
        assert "preferences" in skill.content.lower()

    def test_preferences_reference_accessible_via_skill(self):
        """references/preferences.md is accessible within the skill directory."""
        skill_dir = DEFAULTS / "adapters" / "claude-code" / "skills"
        registry = SkillRegistry(skill_dir)

        skill = registry.get("user-alignment")
        ref_path = skill.dir_path / "references" / "preferences.md"
        assert ref_path.exists()

        content = ref_path.read_text()
        assert "Confidence" in content
        assert "knowledge/user/preferences/" in content

    def test_skill_symlink_includes_references(self, tmp_path):
        """_build_skills_dir creates symlinks that expose references/preferences.md."""
        skill_dir = DEFAULTS / "adapters" / "claude-code" / "skills"
        registry = SkillRegistry(skill_dir)
        adapter = ClaudeCodeAdapter(registry, user_dir=DEFAULTS.parent)

        tmp_dir = adapter._build_skills_dir(["user-alignment"])
        try:
            symlinked_ref = (
                Path(tmp_dir) / ".claude" / "skills" / "user-alignment"
                / "references" / "preferences.md"
            )
            assert symlinked_ref.exists()
            assert "Preference Beliefs Reference" in symlinked_ref.read_text()
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_consolidator_instance_has_user_alignment_skill(self):
        """memory-consolidator.yaml includes user-alignment in its skills list."""
        import yaml

        instance_path = DEFAULTS / "adapters" / "claude-code" / "instances" / "memory-consolidator.yaml"
        config = yaml.safe_load(instance_path.read_text())
        assert "user-alignment" in config["config"]["skills"]


# --- A4: CAMBIUM_DATA_DIR env var ---


class TestDataDirEnvVar:
    """Adapter propagates CAMBIUM_DATA_DIR to routine sessions."""

    def test_adapter_sets_data_dir_env(self, tmp_path: Path):
        """ClaudeCodeAdapter with data_dir sets CAMBIUM_DATA_DIR in env."""
        skill_registry = SkillRegistry()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        adapter = ClaudeCodeAdapter(skill_registry, user_dir=tmp_path, data_dir=data_dir)

        captured_env = {}

        def mock_popen(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.stdout = iter([])
            proc.stderr = MagicMock()
            proc.stderr.read.return_value = ""
            proc.wait.return_value = 0
            proc.returncode = 0
            return proc

        instance = AdapterInstance(
            name="test-instance",
            adapter_type="claude-code",
            config={"model": "haiku", "skills": []},
        )

        with patch("cambium.adapters.claude_code.subprocess.Popen", side_effect=mock_popen):
            adapter.send_message(
                instance=instance,
                user_message="test",
                session_id="test-session",
                session_token="test-token",
                api_base_url="http://localhost:8350",
                live=True,
            )

        assert "CAMBIUM_DATA_DIR" in captured_env
        assert captured_env["CAMBIUM_DATA_DIR"] == str(data_dir)

    def test_adapter_without_data_dir_skips_env(self, tmp_path: Path):
        """Without data_dir, CAMBIUM_DATA_DIR should not be set."""
        skill_registry = SkillRegistry()
        adapter = ClaudeCodeAdapter(skill_registry, user_dir=tmp_path, data_dir=None)

        captured_env = {}

        def mock_popen(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.stdout = iter([])
            proc.stderr = MagicMock()
            proc.stderr.read.return_value = ""
            proc.wait.return_value = 0
            proc.returncode = 0
            return proc

        instance = AdapterInstance(
            name="test-instance",
            adapter_type="claude-code",
            config={"model": "haiku", "skills": []},
        )

        with patch("cambium.adapters.claude_code.subprocess.Popen", side_effect=mock_popen):
            adapter.send_message(
                instance=instance,
                user_message="test",
                session_id="test-session",
                session_token="test-token",
                api_base_url="http://localhost:8350",
                live=True,
            )

        assert "CAMBIUM_DATA_DIR" not in captured_env
