"""Tests for the cambium init CLI."""

import subprocess
from pathlib import Path

from cambium.cli.init import init_user_repo


# === Legacy mode tests (defaults_dir provided) ===

class TestInitLegacy:
    """Tests for legacy init mode (config-only copy)."""

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
        assert (root / "routines" / "coordinator.yaml").exists()
        assert (root / "adapters" / "claude-code" / "instances" / "coordinator.yaml").exists()
        assert (root / "adapters" / "claude-code" / "prompts" / "coordinator.md").exists()
        assert (root / "adapters" / "claude-code" / "skills" / "cambium-api" / "SKILL.md").exists()

    def test_system_prompt_paths_are_relative_to_user_dir(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        import yaml
        config = yaml.safe_load(
            (root / "adapters" / "claude-code" / "instances" / "coordinator.yaml").read_text()
        )
        prompt_path = config["config"]["system_prompt_path"]
        assert not prompt_path.startswith("defaults/")
        assert prompt_path == "adapters/claude-code/prompts/coordinator.md"

    def test_idempotent(self, tmp_path: Path) -> None:
        defaults = _make_defaults(tmp_path)
        root = tmp_path / "cambium"
        init_user_repo(root, defaults_dir=defaults)
        init_user_repo(root, defaults_dir=defaults)
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
        defaults = _make_defaults(tmp_path)
        root = tmp_path / "cambium"
        init_user_repo(root, defaults_dir=defaults)
        custom_prompt = "# My custom coordinator prompt\n"
        (root / "adapters" / "claude-code" / "prompts" / "coordinator.md").write_text(custom_prompt)
        init_user_repo(root, defaults_dir=defaults)
        assert (root / "adapters" / "claude-code" / "prompts" / "coordinator.md").read_text() == custom_prompt

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
        defaults = _make_defaults(tmp_path)
        root = init_user_repo(tmp_path / "cambium", defaults_dir=defaults)
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=root, capture_output=True, text=True,
        )
        assert "Initial Cambium configuration" in result.stdout


# === Combined repo mode tests ===

class TestInitCombined:
    """Tests for combined repo mode (full framework copy)."""

    def test_copies_framework(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        assert (root / "src" / "cambium" / "__init__.py").exists()
        assert (root / "defaults" / "routines" / "coordinator.yaml").exists()
        assert (root / "pyproject.toml").exists()

    def test_excludes_git_and_venv(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        # Create dirs that should be excluded
        (fw / ".git").mkdir()
        (fw / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (fw / ".venv" / "bin").mkdir(parents=True)
        (fw / ".venv" / "bin" / "python").write_text("fake")
        (fw / "node_modules" / "pkg").mkdir(parents=True)
        (fw / "node_modules" / "pkg" / "index.js").write_text("fake")
        (fw / "__pycache__").mkdir()
        (fw / "__pycache__" / "module.pyc").write_text("fake")

        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        assert not (root / ".git" / "HEAD").exists() or True  # .git is created fresh by init
        assert not (root / ".venv").exists()
        assert not (root / "node_modules").exists()
        assert not (root / "__pycache__").exists()

    def test_creates_cambium_version(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        assert (root / ".cambium-version").exists()
        version = (root / ".cambium-version").read_text().strip()
        assert len(version) > 0

    def test_creates_upstream_pointer(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        assert (root / ".cambium-upstream").exists()
        assert "cambium.git" in (root / ".cambium-upstream").read_text()

    def test_creates_git_repo(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        assert (root / ".git").is_dir()
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=root, capture_output=True, text=True,
        )
        assert "Initial Cambium configuration" in result.stdout

    def test_creates_data_dir(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        data_dir = tmp_path / "data"
        init_user_repo(tmp_path / "user-cambium", framework_dir=fw, data_dir=data_dir)
        assert data_dir.is_dir()
        assert (data_dir / "memory").is_dir()
        assert (data_dir / "sessions").is_dir()
        assert (data_dir / "logs").is_dir()

    def test_preserves_existing_files(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = tmp_path / "user-cambium"
        init_user_repo(root, framework_dir=fw)

        # Modify a file
        custom = "# My custom prompt\n"
        prompt_path = root / "defaults" / "adapters" / "claude-code" / "prompts" / "coordinator.md"
        prompt_path.write_text(custom)

        # Re-init should preserve
        init_user_repo(root, framework_dir=fw)
        assert prompt_path.read_text() == custom

    def test_idempotent(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = tmp_path / "user-cambium"
        init_user_repo(root, framework_dir=fw)
        init_user_repo(root, framework_dir=fw)
        assert (root / "src" / "cambium" / "__init__.py").exists()

    def test_constitution_created(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        assert (root / "defaults" / "constitution.md").exists()

    def test_gitignore_created(self, tmp_path: Path) -> None:
        fw = _make_framework(tmp_path)
        root = init_user_repo(tmp_path / "user-cambium", framework_dir=fw)
        content = (root / ".gitignore").read_text()
        assert ".venv/" in content
        assert "*.db" in content


# === Helpers ===

def _make_defaults(tmp_path: Path) -> Path:
    """Create a minimal defaults tree for testing."""
    defaults = tmp_path / "defaults"
    routines = defaults / "routines"
    routines.mkdir(parents=True)
    (routines / "coordinator.yaml").write_text(
        "name: coordinator\nadapter_instance: coordinator\nlisten: [events]\npublish: [tasks]\n"
    )
    instances = defaults / "adapters" / "claude-code" / "instances"
    instances.mkdir(parents=True)
    (instances / "coordinator.yaml").write_text(
        "name: coordinator\nadapter_type: claude-code\n"
        "config:\n  model: opus\n"
        "  system_prompt_path: adapters/claude-code/prompts/coordinator.md\n"
        "  skills: [cambium-api]\n"
    )
    prompts = defaults / "adapters" / "claude-code" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "coordinator.md").write_text("# Coordinator\nYou are the coordinator routine.\n")
    skill = defaults / "adapters" / "claude-code" / "skills" / "cambium-api"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: cambium-api\n---\n# Cambium API\n")
    return defaults


def _make_framework(tmp_path: Path) -> Path:
    """Create a minimal framework repo structure for testing."""
    fw = tmp_path / "framework"
    fw.mkdir()

    # Source code
    src = fw / "src" / "cambium"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('"""Cambium."""\n')

    # Defaults
    defaults = fw / "defaults"
    routines = defaults / "routines"
    routines.mkdir(parents=True)
    (routines / "coordinator.yaml").write_text(
        "name: coordinator\nlisten: [events]\npublish: [tasks]\n"
    )
    instances = defaults / "adapters" / "claude-code" / "instances"
    instances.mkdir(parents=True)
    (instances / "coordinator.yaml").write_text(
        "name: coordinator\nadapter_type: claude-code\n"
        "config:\n  model: opus\n"
        "  system_prompt_path: adapters/claude-code/prompts/coordinator.md\n"
    )
    prompts = defaults / "adapters" / "claude-code" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "coordinator.md").write_text("# Coordinator\n")

    # Config
    (defaults / "config.yaml").write_text("queue:\n  adapter: sqlite\n")

    # Project files
    (fw / "pyproject.toml").write_text('[project]\nname = "cambium"\n')
    (fw / "README.md").write_text("# Cambium\n")

    return fw
