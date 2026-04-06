"""Tests for seedling routine definitions."""

from pathlib import Path
from cambium.models.routine import RoutineRegistry
from cambium.adapters.base import AdapterInstanceRegistry


ROUTINES_DIR = Path(__file__).parent.parent / "defaults" / "routines"
INSTANCES_DIR = Path(__file__).parent.parent / "defaults" / "adapters" / "claude-code" / "instances"
EXPECTED_ROUTINES = [
    "coordinator", "planner", "executor", "reviewer",
    "interlocutor", "session-summarizer", "sentry", "memory-consolidator",
]


class TestSeedlingRoutines:
    def test_all_routines_parse(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        assert len(registry.all()) == 8

    def test_expected_names(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        names = sorted([r.name for r in registry.all()])
        assert names == sorted(EXPECTED_ROUTINES)

    def test_listen_populated(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        for routine in registry.all():
            if routine.name == "interlocutor":
                # Interlocutor is API-driven — no listen channels by design
                continue
            assert len(routine.listen) > 0, f"{routine.name} has no channel subscriptions"

    def test_publish_populated(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        for routine in registry.all():
            assert len(routine.publish) > 0, f"{routine.name} has no publish channels"

    def test_adapter_instances_exist(self) -> None:
        """Every routine references an adapter instance that exists."""
        routine_reg = RoutineRegistry(ROUTINES_DIR)
        instance_reg = AdapterInstanceRegistry(INSTANCES_DIR)
        for routine in routine_reg.all():
            inst = instance_reg.get(routine.adapter_instance)
            assert inst is not None, f"Missing adapter instance '{routine.adapter_instance}' for routine '{routine.name}'"

    def test_executor_routine_exists(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        executor = registry.get("executor")
        assert executor is not None
        assert "tasks" in executor.listen

    def test_interlocutor_routine_exists(self) -> None:
        registry = RoutineRegistry(ROUTINES_DIR)
        interlocutor = registry.get("interlocutor")
        assert interlocutor is not None
        assert interlocutor.listen == []

    def test_channel_cascade_coverage(self) -> None:
        """Verify that published channels have listeners (no dead-letter messages)."""
        registry = RoutineRegistry(ROUTINES_DIR)
        all_listened = set(registry.subscribed_channels())
        all_published: set[str] = set()
        for r in registry.all():
            all_published.update(r.publish)
        # External/system-consumed channels don't need internal listeners
        external = {"schedule", "thoughts", "input_needed"}
        internal_published = all_published - external
        unhandled = internal_published - all_listened
        assert not unhandled, f"Published channels with no listener: {unhandled}"
