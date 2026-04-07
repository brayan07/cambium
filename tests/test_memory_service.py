"""Tests for the memory service — directory init and consolidator state."""

from __future__ import annotations

import subprocess

from cambium.memory.service import MemoryService


class TestInitialization:
    def test_creates_directory_structure(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        mem = svc.path

        assert (mem / "sessions").is_dir()
        assert (mem / "digests" / "daily").is_dir()
        assert (mem / "digests" / "weekly").is_dir()
        assert (mem / "digests" / "monthly").is_dir()
        assert (mem / "knowledge" / "user").is_dir()
        assert (mem / "library").is_dir()

    def test_creates_seed_files(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        mem = svc.path

        assert (mem / "_index.md").exists()
        assert (mem / "knowledge" / "_index.md").exists()
        assert (mem / "knowledge" / "user" / "_index.md").exists()
        assert (mem / "library" / "_index.md").exists()
        assert (mem / ".consolidator-state.md").exists()

    def test_initializes_git_repo(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        assert (svc.path / ".git").is_dir()

    def test_initial_commit_exists(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=svc.path,
            capture_output=True,
            text=True,
        )
        assert "Initialize memory directory" in result.stdout


class TestIdempotency:
    def test_double_init_does_not_error(self, tmp_path):
        mem_dir = tmp_path / "memory"
        svc1 = MemoryService(mem_dir)
        svc2 = MemoryService(mem_dir)
        assert svc2.path == svc1.path

    def test_double_init_preserves_content(self, tmp_path):
        mem_dir = tmp_path / "memory"
        svc = MemoryService(mem_dir)

        # Write custom content
        (svc.path / "_index.md").write_text("# Custom content")

        # Re-init should not overwrite
        svc2 = MemoryService(mem_dir)
        assert (svc2.path / "_index.md").read_text() == "# Custom content"


class TestConsolidatorState:
    def test_initial_state_is_empty_values(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        state = svc.get_consolidator_state()
        assert state.get("last_session_processed") is None
        assert state.get("last_daily_digest") is None

    def test_update_merges_state(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        svc.update_consolidator_state({"last_session_processed": "2026-04-06T10:00:00Z"})

        state = svc.get_consolidator_state()
        assert state["last_session_processed"] == "2026-04-06T10:00:00Z"
        # Other keys should still be present
        assert "last_daily_digest" in state

    def test_update_preserves_existing_keys(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        svc.update_consolidator_state({"last_session_processed": "t1"})
        svc.update_consolidator_state({"last_daily_digest": "2026-04-06"})

        state = svc.get_consolidator_state()
        assert state["last_session_processed"] == "t1"
        assert state["last_daily_digest"] == "2026-04-06"

    def test_update_persists_across_reads(self, tmp_path):
        mem_dir = tmp_path / "memory"
        svc = MemoryService(mem_dir)
        svc.update_consolidator_state({"last_hourly_scan": "2026-04-06T12:00:00Z"})

        # Create new service instance (simulates new session)
        svc2 = MemoryService(mem_dir)
        state = svc2.get_consolidator_state()
        assert state["last_hourly_scan"] == "2026-04-06T12:00:00Z"


class TestGitRepo:
    def test_consolidator_update_creates_commit(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")

        # Count initial commits
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=svc.path, capture_output=True, text=True,
        )
        initial_count = int(result.stdout.strip())

        svc.update_consolidator_state({"last_session_processed": "test"})

        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=svc.path, capture_output=True, text=True,
        )
        new_count = int(result.stdout.strip())
        assert new_count == initial_count + 1

    def test_no_commit_if_state_unchanged(self, tmp_path):
        svc = MemoryService(tmp_path / "memory")
        svc.update_consolidator_state({"last_session_processed": "t1"})

        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=svc.path, capture_output=True, text=True,
        )
        count_after_first = int(result.stdout.strip())

        # Update with same value
        svc.update_consolidator_state({"last_session_processed": "t1"})

        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=svc.path, capture_output=True, text=True,
        )
        count_after_second = int(result.stdout.strip())
        assert count_after_second == count_after_first


class TestPath:
    def test_path_returns_correct_directory(self, tmp_path):
        mem_dir = tmp_path / "memory"
        svc = MemoryService(mem_dir)
        assert svc.path == mem_dir
