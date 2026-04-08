"""Tests for constitution template and env var propagation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from cambium.cli.init import init_user_repo


# --- Template propagation ---


class TestConstitutionTemplate:
    """Init creates constitution.md with the full template content."""

    def test_combined_init_uses_template(self, tmp_path: Path):
        """Combined-repo init should produce a constitution with all 4 sections."""
        fw = _make_framework_with_template(tmp_path)
        root = init_user_repo(tmp_path / "user-repo", framework_dir=fw)

        constitution = (root / "defaults" / "constitution.md").read_text()
        assert "## Goals" in constitution
        assert "## Values" in constitution
        assert "## Projects" in constitution
        assert "## Working Style" in constitution

    def test_legacy_init_uses_template(self, tmp_path: Path):
        """Legacy init should produce a constitution with all 4 sections."""
        defaults = _make_defaults_with_template(tmp_path)
        root = init_user_repo(tmp_path / "user-repo", defaults_dir=defaults)

        constitution = (root / "constitution.md").read_text()
        assert "## Goals" in constitution
        assert "## Values" in constitution
        assert "## Projects" in constitution
        assert "## Working Style" in constitution

    def test_fallback_when_template_missing(self, tmp_path: Path):
        """Without the template file, init falls back to stub content."""
        # Patch _get_defaults_dir to point to a dir with no template
        empty_defaults = tmp_path / "empty-defaults"
        empty_defaults.mkdir()

        fw = _make_framework_bare(tmp_path)
        with patch("cambium.cli.init._get_defaults_dir", return_value=empty_defaults):
            root = init_user_repo(tmp_path / "user-repo", framework_dir=fw)

        constitution = (root / "defaults" / "constitution.md").read_text()
        assert "# Constitution" in constitution
        # Stub doesn't have the 4-section structure
        assert "## Goals" not in constitution


# --- Env var propagation ---


class TestConfigDirEnvVar:
    """The adapter exposes CAMBIUM_CONFIG_DIR to routine sessions."""

    def test_adapter_sets_config_dir_env(self, tmp_path: Path):
        """ClaudeCodeAdapter should include CAMBIUM_CONFIG_DIR in subprocess env."""
        from cambium.adapters.claude_code import ClaudeCodeAdapter
        from cambium.adapters.base import AdapterInstance
        from cambium.models.skill import SkillRegistry

        skill_registry = SkillRegistry()
        adapter = ClaudeCodeAdapter(skill_registry, user_dir=tmp_path)

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
                live=True,  # Must be True — live=False uses _mock_send
            )

        assert "CAMBIUM_CONFIG_DIR" in captured_env
        assert captured_env["CAMBIUM_CONFIG_DIR"] == str(tmp_path)

    def test_adapter_without_user_dir_skips_env(self, tmp_path: Path):
        """Without user_dir, CAMBIUM_CONFIG_DIR should not be set."""
        from cambium.adapters.claude_code import ClaudeCodeAdapter
        from cambium.adapters.base import AdapterInstance
        from cambium.models.skill import SkillRegistry

        skill_registry = SkillRegistry()
        adapter = ClaudeCodeAdapter(skill_registry, user_dir=None)

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
                live=True,  # Must be True — live=False uses _mock_send
            )

        assert "CAMBIUM_CONFIG_DIR" not in captured_env


# --- Helpers ---


_TEMPLATE = """\
# Constitution

## Goals
<!-- What are you trying to achieve? List 2-5 overarching goals. -->

## Values
<!-- What principles guide your decisions? What trade-offs do you make? -->

## Projects
<!-- What long-term projects or areas of focus matter to you? -->

## Working Style
<!-- How do you prefer to work? What conditions help you do your best? -->
"""


def _make_framework_with_template(tmp_path: Path) -> Path:
    """Framework repo with constitution template."""
    fw = tmp_path / "framework"
    fw.mkdir()
    (fw / "src" / "cambium").mkdir(parents=True)
    (fw / "src" / "cambium" / "__init__.py").write_text('"""Cambium."""\n')

    defaults = fw / "defaults"
    (defaults / "routines").mkdir(parents=True)
    (defaults / "routines" / "coordinator.yaml").write_text(
        "name: coordinator\nlisten: [events]\npublish: [tasks]\n"
    )
    (defaults / "config.yaml").write_text("queue:\n  adapter: sqlite\n")
    (defaults / "constitution-template.md").write_text(_TEMPLATE)

    (fw / "pyproject.toml").write_text('[project]\nname = "cambium"\n')
    return fw


def _make_framework_bare(tmp_path: Path) -> Path:
    """Framework repo WITHOUT constitution template."""
    fw = tmp_path / "framework-bare"
    fw.mkdir()
    (fw / "src" / "cambium").mkdir(parents=True)
    (fw / "src" / "cambium" / "__init__.py").write_text('"""Cambium."""\n')

    defaults = fw / "defaults"
    (defaults / "routines").mkdir(parents=True)
    (defaults / "routines" / "coordinator.yaml").write_text(
        "name: coordinator\nlisten: [events]\npublish: [tasks]\n"
    )
    (defaults / "config.yaml").write_text("queue:\n  adapter: sqlite\n")

    (fw / "pyproject.toml").write_text('[project]\nname = "cambium"\n')
    return fw


def _make_defaults_with_template(tmp_path: Path) -> Path:
    """Minimal defaults dir with constitution template for legacy init."""
    defaults = tmp_path / "defaults"
    (defaults / "routines").mkdir(parents=True)
    (defaults / "routines" / "coordinator.yaml").write_text(
        "name: coordinator\nlisten: [events]\npublish: [tasks]\n"
    )
    (defaults / "constitution-template.md").write_text(_TEMPLATE)
    return defaults
