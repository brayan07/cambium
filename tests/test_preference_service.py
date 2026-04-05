"""Tests for preference service layer — signals, cases, context building."""

import pytest

from cambium.preference.model import Dimension, PreferenceCase
from cambium.preference.service import PreferenceService
from cambium.preference.store import PreferenceStore
from cambium.work_item.model import WorkItem, WorkItemStatus


def _make_service() -> PreferenceService:
    store = PreferenceStore()
    service = PreferenceService(store=store)
    service.initialize_defaults()
    return service


def _make_work_item(**kwargs) -> WorkItem:
    defaults = dict(
        title="Test task",
        description="A test",
        context={"domain": "career", "task_type": "research"},
        priority=3,
    )
    defaults.update(kwargs)
    item = WorkItem.create(**defaults)
    item.status = WorkItemStatus.COMPLETED
    item.result = "Some result output"
    return item


class TestInitializeDefaults:
    def test_creates_dimensions(self):
        service = _make_service()
        dims = service.store.list_dimensions()
        assert len(dims) == 5
        names = {d.name for d in dims}
        assert "research_depth" in names
        assert "autonomy_comfort" in names
        assert "quality_bar" in names
        assert "brevity" in names
        assert "action_bias" in names

    def test_creates_objectives(self):
        service = _make_service()
        objs = service.store.list_objectives()
        assert len(objs) == 5
        names = {o.name for o in objs}
        assert "mood" in names
        assert "mental_clarity" in names

    def test_idempotent(self):
        service = _make_service()
        service.initialize_defaults()  # second call
        assert len(service.store.list_dimensions()) == 5

    def test_initial_states_set(self):
        service = _make_service()
        dim = service.store.get_dimension_by_name("research_depth")
        state = service.store.get_state(dim.id, "global")
        assert state is not None
        assert 0.6 < state.mean < 0.7


class TestProcessReview:
    def test_accepted_creates_signals(self):
        service = _make_service()
        item = _make_work_item()

        signals = service.process_review(item, "accepted")
        # Should create signals for multiple dimensions
        assert len(signals) > 0
        # All signals should be review_accepted type
        assert all(s.signal_type == "review_accepted" for s in signals)

    def test_rejected_with_feedback_shifts_posterior(self):
        service = _make_service()
        item = _make_work_item()

        # Get initial state
        dim = service.store.get_dimension_by_name("research_depth")
        initial = service.store.get_state(dim.id, "global")

        # Reject with "too shallow" feedback
        signals = service.process_review(item, "rejected", feedback="Too shallow, needs more sources")

        # Should have a research_depth signal
        depth_signals = [s for s in signals if s.dimension_id == dim.id]
        assert len(depth_signals) > 0

        # Posterior should shift toward higher depth (observation=0.85)
        updated = service.store.get_state(dim.id, "global")
        assert updated.mean > initial.mean

    def test_rejected_too_verbose_shifts_brevity(self):
        service = _make_service()
        item = _make_work_item()

        dim = service.store.get_dimension_by_name("brevity")
        initial = service.store.get_state(dim.id, "global")

        service.process_review(item, "rejected", feedback="Way too verbose, just give me the answer")

        updated = service.store.get_state(dim.id, "global")
        assert updated.mean > initial.mean  # brevity increases

    def test_rejected_no_feedback_emits_quality_signal(self):
        service = _make_service()
        item = _make_work_item()

        signals = service.process_review(item, "rejected", feedback="")
        dim = service.store.get_dimension_by_name("quality_bar")
        quality_signals = [s for s in signals if s.dimension_id == dim.id]
        assert len(quality_signals) == 1

    def test_multiple_reviews_converge(self):
        service = _make_service()
        dim = service.store.get_dimension_by_name("research_depth")

        # 5 rejections saying "too shallow"
        for _ in range(5):
            item = _make_work_item()
            service.process_review(item, "rejected", feedback="Too shallow")

        state = service.store.get_state(dim.id, "global")
        # Should be significantly higher than initial 0.65
        assert state.mean > 0.75
        # Variance should be tight
        assert state.variance < 0.05


class TestBuildPreferenceContext:
    def test_returns_dimensions_and_cases(self):
        service = _make_service()
        item = _make_work_item()

        context = service.build_preference_context(item)
        assert "dimensions" in context
        assert "cases" in context
        assert "prompt_text" in context
        assert len(context["dimensions"]) > 0

    def test_prompt_text_includes_dimension_names(self):
        service = _make_service()
        item = _make_work_item()

        context = service.build_preference_context(item)
        text = context["prompt_text"]
        assert "quality_bar" in text
        assert "brevity" in text

    def test_includes_cases_when_available(self):
        service = _make_service()
        # Create a case
        case_item = _make_work_item()
        service.create_case_from_review(case_item, "accepted", lesson="Test lesson")

        # Build context for similar item
        item = _make_work_item()
        context = service.build_preference_context(item)
        assert len(context["cases"]) >= 1


class TestCaseManagement:
    def test_create_case_from_accepted(self):
        service = _make_service()
        item = _make_work_item()

        case = service.create_case_from_review(item, "accepted", lesson="Good research depth")
        assert case.signal_direction == 1.0
        assert case.lesson == "Good research depth"
        assert case.domain == "career"

    def test_create_case_from_rejected(self):
        service = _make_service()
        item = _make_work_item()

        case = service.create_case_from_review(
            item, "rejected", feedback="Too shallow", lesson="Need primary sources",
        )
        assert case.signal_direction == -1.0
        assert case.feedback == "Too shallow"

    def test_case_without_lesson_uses_feedback(self):
        service = _make_service()
        item = _make_work_item()

        case = service.create_case_from_review(item, "rejected", feedback="Bad output")
        assert case.lesson == "Bad output"

    def test_record_case_outcome(self):
        service = _make_service()
        item = _make_work_item()
        case = service.create_case_from_review(item, "accepted", lesson="test")

        service.record_case_outcome(case.id, task_approved=True)
        got = service.store.get_case(case.id)
        assert got.usefulness_score > 0.5

        service.record_case_outcome(case.id, task_approved=False)
        service.record_case_outcome(case.id, task_approved=False)
        got = service.store.get_case(case.id)
        assert got.usefulness_score < 0.5


class TestObjectives:
    def test_record_objective(self):
        service = _make_service()
        report = service.record_objective("mood", 4.0, notes="Pretty good day")
        assert report.value == 4.0

    def test_nonexistent_objective_raises(self):
        service = _make_service()
        with pytest.raises(ValueError, match="not found"):
            service.record_objective("nonexistent", 3.0)
