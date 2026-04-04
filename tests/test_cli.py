"""Tests for the cambium init CLI."""

from pathlib import Path
from cambium.cli.init import init_user_repo


class TestInitUserRepo:
    def test_creates_structure(self, tmp_path: Path) -> None:
        root = init_user_repo(tmp_path / "cambium")
        assert root.exists()
        assert (root / "config.yaml").exists()
        assert (root / "constitution.md").exists()
        assert (root / ".gitignore").exists()
        assert (root / "skills").is_dir()
        assert (root / "routines").is_dir()
        assert (root / "knowledge").is_dir()
        assert (root / "data/memory").is_dir()
        assert (root / "data/sessions").is_dir()
        assert (root / "data/logs").is_dir()
        assert (root / ".git").is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        root = tmp_path / "cambium"
        init_user_repo(root)
        init_user_repo(root)  # second call should not raise
        assert (root / "config.yaml").exists()

    def test_preserves_existing_config(self, tmp_path: Path) -> None:
        root = tmp_path / "cambium"
        init_user_repo(root)
        custom = "custom: true\n"
        (root / "config.yaml").write_text(custom)
        init_user_repo(root)
        assert (root / "config.yaml").read_text() == custom

    def test_gitignore_content(self, tmp_path: Path) -> None:
        root = init_user_repo(tmp_path / "cambium")
        content = (root / ".gitignore").read_text()
        assert "data/" in content
        assert "__pycache__/" in content

    def test_config_yaml_content(self, tmp_path: Path) -> None:
        root = init_user_repo(tmp_path / "cambium")
        import yaml
        config = yaml.safe_load((root / "config.yaml").read_text())
        assert config["queue"]["adapter"] == "sqlite"
        assert config["queue"]["database"] == "data/cambium.db"
