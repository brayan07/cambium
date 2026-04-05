"""Tests for preference store persistence layer."""

import pytest

from cambium.preference.model import (
    Dimension,
    ObjectiveDefinition,
    ObjectiveReport,
    PreferenceCase,
)
from cambium.preference.store import PreferenceStore


class TestDimensions:
    def test_create_and_get(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth", description="Research depth")
        store.create_dimension(dim)

        got = store.get_dimension(dim.id)
        assert got is not None
        assert got.name == "depth"

    def test_get_by_name(self):
        store = PreferenceStore()
        dim = Dimension.create(name="brevity", anchors={"low": "verbose", "high": "terse"})
        store.create_dimension(dim)

        got = store.get_dimension_by_name("brevity")
        assert got is not None
        assert got.anchors["high"] == "terse"

    def test_list_dimensions(self):
        store = PreferenceStore()
        store.create_dimension(Dimension.create(name="alpha"))
        store.create_dimension(Dimension.create(name="beta"))

        dims = store.list_dimensions()
        assert len(dims) == 2
        assert dims[0].name == "alpha"  # ordered by name

    def test_duplicate_name_raises(self):
        store = PreferenceStore()
        store.create_dimension(Dimension.create(name="dup"))
        with pytest.raises(Exception):
            store.create_dimension(Dimension.create(name="dup"))


class TestPreferenceState:
    def test_set_and_get(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.65, 0.15)

        state = store.get_state(dim.id, "global")
        assert state is not None
        assert state.mean == 0.65
        assert state.variance == 0.15

    def test_upsert(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.2)
        store.set_state(dim.id, "global", 0.7, 0.1)

        state = store.get_state(dim.id, "global")
        assert state.mean == 0.7

    def test_resolve_state_hierarchy(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.2)
        store.set_state(dim.id, "domain:career", 0.8, 0.1)

        # Specific context found
        state = store.resolve_state(dim.id, ["domain:career", "global"])
        assert state.mean == 0.8

        # Falls back to global
        state = store.resolve_state(dim.id, ["domain:personal", "global"])
        assert state.mean == 0.5

        # No match
        state = store.resolve_state(dim.id, ["domain:personal"])
        assert state is None

    def test_get_nonexistent_returns_none(self):
        store = PreferenceStore()
        assert store.get_state("fake", "global") is None


class TestPosteriorUpdate:
    def test_basic_update(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.15)

        signal = store.update_posterior(
            dim.id, "global", observation=0.8, obs_variance=0.05,
            signal_type="review_rejected", source_item_id="item-1",
        )

        # Posterior should shift toward observation
        assert signal.posterior_mean > 0.5
        assert signal.posterior_variance < 0.15
        assert signal.prior_mean == 0.5

        # State should be updated
        state = store.get_state(dim.id, "global")
        assert state.mean == signal.posterior_mean
        assert state.update_count == 1

    def test_low_obs_variance_dominates(self):
        """An explicit statement (obs_var=0.01) should move the posterior strongly."""
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.15)

        signal = store.update_posterior(
            dim.id, "global", observation=0.9, obs_variance=0.01,
        )

        # Should be very close to 0.9
        assert signal.posterior_mean > 0.85

    def test_high_obs_variance_weak_signal(self):
        """An approval (obs_var=0.20) should barely move the posterior."""
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.15)

        signal = store.update_posterior(
            dim.id, "global", observation=0.8, obs_variance=0.20,
        )

        # Should move only slightly
        assert 0.5 < signal.posterior_mean < 0.7

    def test_multiple_updates_reduce_variance(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.20)

        for _ in range(5):
            store.update_posterior(dim.id, "global", observation=0.7, obs_variance=0.10)

        state = store.get_state(dim.id, "global")
        assert state.variance < 0.05  # much tighter after 5 signals
        assert state.update_count == 5

    def test_no_state_raises(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        # No state set
        with pytest.raises(ValueError, match="No state"):
            store.update_posterior(dim.id, "domain:career", observation=0.5, obs_variance=0.1)


class TestSignals:
    def test_signals_recorded_on_update(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.15)

        store.update_posterior(
            dim.id, "global", observation=0.8, obs_variance=0.05,
            signal_type="review_rejected", source_item_id="item-1",
            raw_data={"feedback": "too shallow"},
        )

        signals = store.get_signals(dimension_id=dim.id)
        assert len(signals) == 1
        assert signals[0].signal_type == "review_rejected"
        assert signals[0].source_item_id == "item-1"
        assert signals[0].raw_data["feedback"] == "too shallow"

    def test_filter_by_source_item(self):
        store = PreferenceStore()
        dim = Dimension.create(name="depth")
        store.create_dimension(dim)
        store.set_state(dim.id, "global", 0.5, 0.15)

        store.update_posterior(dim.id, "global", 0.8, 0.1, source_item_id="a")
        store.update_posterior(dim.id, "global", 0.3, 0.1, source_item_id="b")

        signals = store.get_signals(source_item_id="a")
        assert len(signals) == 1
        assert signals[0].source_item_id == "a"


class TestCases:
    def test_create_and_get(self):
        store = PreferenceStore()
        case = PreferenceCase.create(
            work_item_id="wi-1", action_summary="did research",
            outcome="accepted", lesson="include primary sources",
            domain="career", task_type="research",
        )
        store.create_case(case)

        got = store.get_case(case.id)
        assert got is not None
        assert got.lesson == "include primary sources"

    def test_query_by_domain(self):
        store = PreferenceStore()
        store.create_case(PreferenceCase.create(
            work_item_id="1", action_summary="a", outcome="o", lesson="l",
            domain="career", task_type="research",
        ))
        store.create_case(PreferenceCase.create(
            work_item_id="2", action_summary="a", outcome="o", lesson="l",
            domain="personal",
        ))

        cases = store.query_cases(domain="career")
        assert len(cases) == 1
        assert cases[0].domain == "career"

    def test_retrieval_count_updates(self):
        store = PreferenceStore()
        case = PreferenceCase.create(
            work_item_id="1", action_summary="a", outcome="o", lesson="l",
        )
        store.create_case(case)
        assert store.get_case(case.id).retrieval_count == 0

        store.update_case_retrieval(case.id)
        assert store.get_case(case.id).retrieval_count == 1

    def test_usefulness_clamped(self):
        store = PreferenceStore()
        case = PreferenceCase.create(
            work_item_id="1", action_summary="a", outcome="o", lesson="l",
        )
        store.create_case(case)

        # Push above 1.0
        for _ in range(20):
            store.update_case_usefulness(case.id, 0.1)
        assert store.get_case(case.id).usefulness_score <= 1.0

        # Push below 0.0
        for _ in range(30):
            store.update_case_usefulness(case.id, -0.1)
        assert store.get_case(case.id).usefulness_score >= 0.0

    def test_archive(self):
        store = PreferenceStore()
        case = PreferenceCase.create(
            work_item_id="1", action_summary="a", outcome="o", lesson="l",
        )
        store.create_case(case)
        store.archive_case(case.id)

        # Not returned by default query
        assert len(store.query_cases()) == 0
        # Returned when asking for archived
        assert len(store.query_cases(archived=True)) == 1


class TestObjectives:
    def test_create_and_list(self):
        store = PreferenceStore()
        obj = ObjectiveDefinition.create(
            name="mood", constitutional_goal="goal:1", cadence="daily",
        )
        store.create_objective(obj)

        objs = store.list_objectives()
        assert len(objs) == 1
        assert objs[0].name == "mood"

    def test_record_and_get_reports(self):
        store = PreferenceStore()
        obj = ObjectiveDefinition.create(name="mood", constitutional_goal="goal:1")
        store.create_objective(obj)

        r1 = ObjectiveReport.create(objective_id=obj.id, value=4.0, notes="good day")
        r2 = ObjectiveReport.create(objective_id=obj.id, value=3.0)
        store.record_objective_report(r1)
        store.record_objective_report(r2)

        reports = store.get_objective_reports(obj.id)
        assert len(reports) == 2

    def test_get_by_name(self):
        store = PreferenceStore()
        obj = ObjectiveDefinition.create(name="clarity", constitutional_goal="goal:1")
        store.create_objective(obj)

        got = store.get_objective_by_name("clarity")
        assert got is not None
        assert got.id == obj.id

        assert store.get_objective_by_name("nonexistent") is None


class TestInterruptionBudget:
    def test_default_budget(self):
        store = PreferenceStore()
        max_q, asked = store.get_budget_today()
        assert max_q == 5
        assert asked == 0

    def test_increment(self):
        store = PreferenceStore()
        store.increment_budget()
        store.increment_budget()

        _, asked = store.get_budget_today()
        assert asked == 2

    def test_reset(self):
        store = PreferenceStore()
        store.increment_budget()
        store.increment_budget()
        store.reset_budget(max_questions=3)

        max_q, asked = store.get_budget_today()
        assert max_q == 3
        assert asked == 0
