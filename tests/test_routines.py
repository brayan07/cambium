"""Tests for seedling routine definitions."""

from pathlib import Path
from cambium.models.routine import RoutineRegistry


ROUTINES_DIR = Path(__file__).parent.parent / "defaults" / "routines"
EXPECTED_ROUTINES = ["triage", "planning", "execution", "review", "reflection", "interactive"]


class TestSeedlingRoutines:
    def test_all_routines_parse(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        assert len(registry.all()) == 6

    def test_expected_names(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        names = sorted(registry.names() if hasattr(registry, 'names') else [r.name for r in registry.all()])
        assert names == sorted(EXPECTED_ROUTINES)

    def test_subscribe_populated(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        for routine in registry.all():
            assert len(routine.subscribe) > 0, f"{routine.name} has no subscriptions"

    def test_emit_populated(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        for routine in registry.all():
            assert len(routine.emit) > 0, f"{routine.name} has no emit types"

    def test_prompt_files_exist(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        for routine in registry.all():
            prompt_path = ROUTINES_DIR / routine.prompt_path
            assert prompt_path.exists(), f"Prompt file missing for {routine.name}: {prompt_path}"

    def test_execution_routine_exists(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        execution = registry.get("execution")
        assert execution is not None
        assert "task_queued" in execution.subscribe

    def test_interactive_routine_exists(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        interactive = registry.get("interactive")
        assert interactive is not None
        assert "user_session_start" in interactive.subscribe

    def test_event_cascade_coverage(self) -> None:
        """Verify that emitted events have subscribers (no dead-letter events)."""
        registry = RoutineRegistry(ROUTINES_DIR)
        all_subscribed = set(registry.subscribed_event_types())
        all_emitted: set[str] = set()
        for r in registry.all():
            all_emitted.update(r.emit)
        # External triggers don't need internal subscribers
        external = {"schedule_daily", "user_session_start", "skill_improvement_proposed"}
        internal_emitted = all_emitted - external
        unhandled = internal_emitted - all_subscribed
        assert not unhandled, f"Emitted events with no subscriber: {unhandled}"
