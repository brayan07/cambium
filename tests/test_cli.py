"""Tests for the cambium init CLI."""

from pathlib import Path
from cambium.cli.init import init_user_repo


class TestInitUserRepo:
    def test_creates_structure(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        assert root.exists()
        assert (root / "config.yaml").exists()
        assert (root / "constitution.md").exists()
        assert (root / ".gitignore").exists()
        assert (root / "knowledge").is_dir()
        assert (root / "data/memory").is_dir()
        assert (root / "data/sessions").is_dir()
        assert (root / "data/logs").is_dir()
        assert (root / ".git").is_dir()

    def test_copies_defaults(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        # Routines
        assert (root / "routines" / "triage.yaml").exists()
        # Adapter instances
        assert (root / "adapters" / "claude-code" / "instances" / "triage.yaml").exists()
        # Adapter prompts
        assert (root / "adapters" / "claude-code" / "prompts" / "triage.md").exists()
        # Skills
        assert (root / "adapters" / "claude-code" / "skills" / "cambium-api" / "SKILL.md").exists()

    def test_system_prompt_paths_are_relative_to_user_dir(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        import yaml
        config = yaml.safe_load(
            (root / "adapters" / "claude-code" / "instances" / "triage.yaml").read_text()
        )
        prompt_path = config["config"]["system_prompt_path"]
        assert not prompt_path.startswith("defaults/")
        assert prompt_path == "adapters/claude-code/prompts/triage.md"

    def test_idempotent(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = tmp_path / "cambium"
        init_user_repo(root, defaults_dir=defaults)
        init_user_repo(root, defaults_dir=defaults)  # second call should not raise
        assert (root / "config.yaml").exists()

    def test_preserves_existing_config(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = tmp_path / "cambium"
        init_user_repo(root, defaults_dir=defaults)
        custom = "custom: true\n"
        (root / "config.yaml").write_text(custom)
        init_user_repo(root, defaults_dir=defaults)
        assert (root / "config.yaml").read_text() == custom

    def test_preserves_existing_defaults(self, tmp_path: Path) -> None:
        """User-modified default files are not overwritten on re-init."""
        defaults = _make_defaults(tmp_path)
        root = tmp_path / "cambium"
        init_user_repo(root, defaults_dir=defaults)
        custom_prompt = "# My custom triage prompt\n"
        (root / "adapters" / "claude-code" / "prompts" / "triage.md").write_text(custom_prompt)
        init_user_repo(root, defaults_dir=defaults)
        assert (root / "adapters" / "claude-code" / "prompts" / "triage.md").read_text() == custom_prompt

    def test_gitignore_content(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        content = (root / ".gitignore").read_text()
        assert "data/" in content
        assert "__pycache__/" in content

    def test_config_yaml_content(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        import yaml
        config = yaml.safe_load((root / "config.yaml").read_text())
        assert config["queue"]["adapter"] == "sqlite"
        assert config["queue"]["database"] == "data/cambium.db"

    def test_initial_git_commit(self, tmp_path: Path) -> None:
        import subprocess
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=root, capture_output=True, text=True,
        )
        assert "Initial Cambium configuration" in result.stdout


def _make_defaults(tmp_path: Path) -> Path:
    """Create a minimal defaults tree for testing."""
    defaults = tmp_path / "defaults"
    # Routine
    routines = defaults / "routines"
    routines.mkdir(parents=True)
    (routines / "triage.yaml").write_text(
        "name: triage\nadapter_instance: triage\nlisten: [goals]\npublish: [tasks]\n"
    )
    # Adapter instance
    instances = defaults / "adapters" / "claude-code" / "instances"
    instances.mkdir(parents=True)
    (instances / "triage.yaml").write_text(
        "name: triage\nadapter_type: claude-code\n"
        "config:\n  model: opus\n"
        "  system_prompt_path: adapters/claude-code/prompts/triage.md\n"
        "  skills: [cambium-api]\n"
    )
    # Prompt
    prompts = defaults / "adapters" / "claude-code" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "triage.md").write_text("# Triage\nYou are the triage routine.\n")
    # Skill
    skill = defaults / "adapters" / "claude-code" / "skills" / "cambium-api"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: cambium-api\n---\n# Cambium API\n")
    return defaults
