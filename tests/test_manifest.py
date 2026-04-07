"""Tests for tunable manifest loading and validation."""

from pathlib import Path

import yaml

from cambium.eval.manifest import TunableManifest, TunableEntry, ProtectedEntry, load_manifest


class TestTunableManifest:
    def test_is_tunable_prompt(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="adapters/claude-code/prompts/*.md", type="prompt")],
        )
        assert m.is_tunable("adapters/claude-code/prompts/coordinator.md")
        assert not m.is_tunable("adapters/claude-code/instances/coordinator.yaml")

    def test_is_tunable_skill(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="adapters/claude-code/skills/*/SKILL.md", type="skill")],
        )
        assert m.is_tunable("adapters/claude-code/skills/cambium-api/SKILL.md")
        assert not m.is_tunable("adapters/claude-code/skills/cambium-api/helper.py")

    def test_is_tunable_routine(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="routines/*.yaml", type="routine_config", fields=["batch_window"])],
        )
        assert m.is_tunable("routines/coordinator.yaml")
        assert not m.is_tunable("routines/nested/deep.yaml")

    def test_protected_overrides_tunable(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="*.yaml", type="config")],
            protected=[ProtectedEntry(path="config.yaml")],
        )
        assert not m.is_tunable("config.yaml")
        assert m.is_tunable("other.yaml")

    def test_validate_override_clean(self):
        m = TunableManifest(
            tunable=[
                TunableEntry(path="adapters/claude-code/prompts/*.md", type="prompt"),
                TunableEntry(path="routines/*.yaml", type="routine_config", fields=["batch_window", "batch_max"]),
            ],
        )
        violations = m.validate_override({
            "adapters/claude-code/prompts/coordinator.md": {"append": "new line"},
            "routines/coordinator.yaml": {"batch_window": 5},
        })
        assert violations == []

    def test_validate_override_protected(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="*.yaml", type="config")],
            protected=[ProtectedEntry(path="config.yaml")],
        )
        violations = m.validate_override({"config.yaml": {"key": "value"}})
        assert len(violations) == 1
        assert "Protected" in violations[0]

    def test_validate_override_not_tunable(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="routines/*.yaml", type="routine_config")],
        )
        violations = m.validate_override({"src/cambium/server/app.py": {"key": "value"}})
        assert len(violations) == 1
        assert "not in tunable" in violations[0]

    def test_validate_override_restricted_fields(self):
        m = TunableManifest(
            tunable=[TunableEntry(
                path="routines/*.yaml",
                type="routine_config",
                fields=["batch_window", "batch_max"],
            )],
        )
        # Valid field
        assert m.validate_override({"routines/coordinator.yaml": {"batch_window": 5}}) == []
        # Invalid field
        violations = m.validate_override({"routines/coordinator.yaml": {"listen": ["events"]}})
        assert len(violations) == 1
        assert "listen" in violations[0]

    def test_get_tunable_entry(self):
        entry = TunableEntry(path="routines/*.yaml", type="routine_config", fields=["batch_window"])
        m = TunableManifest(tunable=[entry])
        result = m.get_tunable_entry("routines/coordinator.yaml")
        assert result is not None
        assert result.type == "routine_config"
        assert result.fields == ["batch_window"]

    def test_get_tunable_entry_protected(self):
        m = TunableManifest(
            tunable=[TunableEntry(path="*.yaml", type="config")],
            protected=[ProtectedEntry(path="config.yaml")],
        )
        assert m.get_tunable_entry("config.yaml") is None

    def test_empty_manifest(self):
        m = TunableManifest()
        assert not m.is_tunable("anything.yaml")
        assert m.validate_override({"file.yaml": {}}) == ["File not in tunable manifest: file.yaml"]


class TestLoadManifest:
    def test_load_from_file(self, tmp_path):
        manifest_data = {
            "tunable": [
                {"path": "prompts/*.md", "type": "prompt"},
                {"path": "routines/*.yaml", "type": "routine_config", "fields": ["batch_window"]},
            ],
            "protected": [
                {"path": "config.yaml"},
            ],
        }
        manifest_path = tmp_path / "tunable-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.safe_dump(manifest_data, f)

        m = load_manifest(tmp_path)
        assert len(m.tunable) == 2
        assert len(m.protected) == 1
        assert m.is_tunable("prompts/coordinator.md")
        assert not m.is_tunable("config.yaml")

    def test_load_missing_file(self, tmp_path):
        m = load_manifest(tmp_path)
        assert len(m.tunable) == 0
        assert len(m.protected) == 0

    def test_load_real_manifest(self):
        """Test loading the actual shipped manifest."""
        defaults = Path(__file__).parent.parent / "defaults"
        if not (defaults / "tunable-manifest.yaml").exists():
            return  # skip if not in full repo
        m = load_manifest(defaults)
        assert len(m.tunable) > 0
        assert m.is_tunable("adapters/claude-code/prompts/coordinator.md")
        assert not m.is_tunable("config.yaml")
