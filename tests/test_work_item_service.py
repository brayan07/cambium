"""Tests for work item service layer."""

import pytest

from cambium.queue.sqlite import SQLiteQueue
from cambium.work_item.model import CompletionMode, RollupMode, WorkItem, WorkItemStatus
from cambium.work_item.service import WorkItemService
from cambium.work_item.store import WorkItemStore


def _make_service() -> tuple[WorkItemService, WorkItemStore, SQLiteQueue]:
    store = WorkItemStore()
    queue = SQLiteQueue()
    service = WorkItemService(store=store, queue=queue)
    return service, store, queue


def _drain(queue: SQLiteQueue, channels: list[str]) -> None:
    """Drain messages from channels to keep tests focused."""
    queue.consume(channels, limit=50)


class TestCreateItem:
    def test_create_publishes_to_plans(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Plan something", actor="coordinator")

        assert item.status == WorkItemStatus.PENDING
        assert store.get(item.id) is not None

        msgs = queue.consume(["plans"], limit=10)
        assert len(msgs) == 1
        assert msgs[0].payload["action"] == "created"
        assert msgs[0].payload["work_item_id"] == item.id


class TestDecompose:
    def test_basic_decomposition(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Big task")
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id,
            [
                {"title": "Step 1", "priority": 2},
                {"title": "Step 2", "priority": 1},
            ],
            actor="planner",
        )

        assert len(children) == 2
        assert all(c.parent_id == parent.id for c in children)

        # Both should be ready (no dependencies)
        for c in children:
            got = store.get(c.id)
            assert got.status == WorkItemStatus.READY

        # Should publish to tasks
        msgs = queue.consume(["tasks"], limit=10)
        assert len(msgs) == 2

    def test_dollar_ref_dependencies(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Ordered work")
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id,
            [
                {"title": "First"},
                {"title": "Second", "depends_on": ["$0"]},
                {"title": "Third", "depends_on": ["$1"]},
            ],
            actor="planner",
        )

        # First has no deps → ready
        assert store.get(children[0].id).status == WorkItemStatus.READY
        # Second depends on first → still pending
        assert store.get(children[1].id).status == WorkItemStatus.PENDING
        # Third depends on second → still pending
        assert store.get(children[2].id).status == WorkItemStatus.PENDING

        # Second's depends_on should reference first's real ID
        assert store.get(children[1].id).depends_on == [children[0].id]

    def test_invalid_dollar_ref_raises(self):
        service, _, queue = _make_service()
        parent = service.create_item(title="Bad refs")
        _drain(queue, ["plans"])

        with pytest.raises(ValueError, match="Invalid \\$N reference"):
            service.decompose(
                parent.id,
                [{"title": "Only child", "depends_on": ["$5"]}],
            )

    def test_nonexistent_parent_raises(self):
        service, _, _ = _make_service()
        with pytest.raises(ValueError, match="not found"):
            service.decompose("ghost", [{"title": "child"}])


class TestRollupAll:
    def test_auto_rollup_all_children(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent", completion_mode=CompletionMode.ALL)
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id, [{"title": "A"}, {"title": "B"}]
        )
        _drain(queue, ["tasks"])

        # Complete and review first child — parent should NOT complete yet
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "done A")
        _drain(queue, ["completions"])
        service.review_item(children[0].id, "accepted", actor="reviewer")
        assert store.get(parent.id).status != WorkItemStatus.COMPLETED

        # Complete and review second child — parent should auto-complete
        service.claim_item(children[1].id, session_id="s2", actor="executor")
        service.complete_item(children[1].id, "done B")
        _drain(queue, ["completions"])
        service.review_item(children[1].id, "accepted", actor="reviewer")
        p = store.get(parent.id)
        assert p.status == WorkItemStatus.COMPLETED
        assert "done A" in p.result
        assert "done B" in p.result
        # Auto-rollup parent inherits review trust
        assert p.reviewed_by == "auto_rollup"

    def test_completed_but_unreviewed_does_not_rollup(self):
        """Parent should NOT complete when children are completed but not reviewed."""
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        _drain(queue, ["plans"])

        _, children = service.decompose(parent.id, [{"title": "Only child"}])
        _drain(queue, ["tasks"])

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "done")

        # Child is completed but not reviewed — parent stays pending
        assert store.get(children[0].id).status == WorkItemStatus.COMPLETED
        assert store.get(children[0].id).reviewed_by is None
        assert store.get(parent.id).status != WorkItemStatus.COMPLETED

    def test_recursive_rollup(self):
        service, store, queue = _make_service()
        root = service.create_item(title="Root")
        _drain(queue, ["plans"])

        _, mid = service.decompose(root.id, [{"title": "Mid"}])
        _drain(queue, ["tasks"])
        _, leaves = service.decompose(mid[0].id, [{"title": "Leaf"}])
        _drain(queue, ["tasks"])

        service.claim_item(leaves[0].id, session_id="s1", actor="executor")
        service.complete_item(leaves[0].id, "leaf done")
        _drain(queue, ["completions"])
        service.review_item(leaves[0].id, "accepted", actor="reviewer")

        # Mid should auto-complete (and inherit review trust)
        assert store.get(mid[0].id).status == WorkItemStatus.COMPLETED
        assert store.get(mid[0].id).reviewed_by == "auto_rollup"
        # Root should auto-complete
        assert store.get(root.id).status == WorkItemStatus.COMPLETED


class TestRollupAny:
    def test_any_mode_completes_on_first_child(self):
        service, store, queue = _make_service()
        parent = service.create_item(
            title="Race", completion_mode=CompletionMode.ANY
        )
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id, [{"title": "A"}, {"title": "B"}]
        )
        _drain(queue, ["tasks"])

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "A wins")
        _drain(queue, ["completions"])
        service.review_item(children[0].id, "accepted", actor="reviewer")
        assert store.get(parent.id).status == WorkItemStatus.COMPLETED


class TestSynthesizeRollup:
    def test_synthesize_publishes_to_plans_after_review(self):
        """Synthesize triggers after review — planner shouldn't synthesize unreviewed work."""
        service, store, queue = _make_service()
        parent = service.create_item(
            title="Synthesize parent",
            rollup_mode=RollupMode.SYNTHESIZE,
        )
        _drain(queue, ["plans"])

        _, children = service.decompose(parent.id, [{"title": "Only child"}])
        _drain(queue, ["tasks"])

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "child result")
        _drain(queue, ["completions"])

        # Before review — no synthesize message yet
        msgs = queue.consume(["plans"], limit=10)
        synthesize_msgs = [m for m in msgs if m.payload.get("action") == "synthesize"]
        assert len(synthesize_msgs) == 0

        # Review triggers synthesize
        service.review_item(children[0].id, "accepted", actor="reviewer")

        # Parent should NOT be completed — planner must synthesize
        assert store.get(parent.id).status != WorkItemStatus.COMPLETED

        # Should publish synthesize message to plans
        msgs = queue.consume(["plans"], limit=10)
        synthesize_msgs = [
            m for m in msgs if m.payload.get("action") == "synthesize"
        ]
        assert len(synthesize_msgs) == 1
        assert synthesize_msgs[0].payload["work_item_id"] == parent.id


class TestFailRetry:
    def test_fail_under_max_retries_to_ready(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id, [{"title": "Retry task", "max_attempts": 3}]
        )
        _drain(queue, ["tasks"])

        # Claim and fail
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        result = service.fail_item(children[0].id, "oops", actor="executor")

        # Should be back to ready for retry
        assert result.status == WorkItemStatus.READY

        # Should publish retry to tasks
        msgs = queue.consume(["tasks"], limit=10)
        assert any(m.payload.get("action") == "retry" for m in msgs)


class TestFailPermanent:
    def test_fail_at_max_attempts_stays_failed(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id, [{"title": "Fragile", "max_attempts": 1}]
        )
        _drain(queue, ["tasks"])

        # Claim (increments attempt_count to 1 = max_attempts)
        service.claim_item(children[0].id, session_id="s1", actor="executor")

        result = service.fail_item(children[0].id, "dead", actor="executor")
        assert result.status == WorkItemStatus.FAILED

        # Should publish failed_permanently to plans
        msgs = queue.consume(["plans"], limit=10)
        assert any(m.payload.get("action") == "failed_permanently" for m in msgs)


class TestReview:
    def test_accepted_sets_reviewed_fields(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Reviewable")
        _drain(queue, ["plans"])

        _, children = service.decompose(parent.id, [{"title": "Child"}])
        _drain(queue, ["tasks"])

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "done")
        _drain(queue, ["completions"])

        # Before review: no reviewed_by
        assert store.get(children[0].id).reviewed_by is None

        service.review_item(children[0].id, "accepted", actor="reviewer")

        # After review: reviewed_by set, parent auto-completed
        child = store.get(children[0].id)
        assert child.reviewed_by == "reviewer"
        assert child.reviewed_at is not None
        assert store.get(parent.id).status == WorkItemStatus.COMPLETED

    def test_rejected_retries(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Review me", max_attempts=3)
        _drain(queue, ["plans"])

        # Move to ready, claim, complete
        store.update_status(item.id, WorkItemStatus.READY)
        service.claim_item(item.id, session_id="s1", actor="executor")
        service.complete_item(item.id, "first attempt")
        _drain(queue, ["completions"])

        # Reject — should go back to ready
        result = service.review_item(
            item.id, verdict="rejected", feedback="Not good enough"
        )
        assert result.status == WorkItemStatus.READY

        # reviewed_by should NOT be set on rejection
        assert store.get(item.id).reviewed_by is None

        # Context should have rejection feedback
        got = store.get(item.id)
        assert got.context["rejection_feedback"] == "Not good enough"

        # Regression: status_forced event must have reason "review_rejection"
        forced = store.get_events(item.id, event_type="status_forced")
        assert len(forced) == 1
        assert forced[0].data["reason"] == "review_rejection"

    def test_invalid_verdict_raises(self):
        service, _, queue = _make_service()
        item = service.create_item(title="Item")
        _drain(queue, ["plans"])

        with pytest.raises(ValueError, match="Invalid verdict"):
            service.review_item(item.id, verdict="maybe")


class TestDependencyResolution:
    def test_completing_and_reviewing_dep_unblocks_dependent(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id,
            [
                {"title": "Dep"},
                {"title": "Dependent", "depends_on": ["$0"]},
            ],
        )
        _drain(queue, ["tasks"])

        # Dependent should be pending
        assert store.get(children[1].id).status == WorkItemStatus.PENDING

        # Complete the dependency — dependent stays pending (not reviewed yet)
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "dep done")
        assert store.get(children[1].id).status == WorkItemStatus.PENDING

        # Review the dependency — NOW dependent becomes ready
        _drain(queue, ["completions"])
        service.review_item(children[0].id, "accepted", actor="reviewer")
        assert store.get(children[1].id).status == WorkItemStatus.READY

    def test_partial_deps_stay_pending(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        _drain(queue, ["plans"])

        _, children = service.decompose(
            parent.id,
            [
                {"title": "A"},
                {"title": "B"},
                {"title": "C", "depends_on": ["$0", "$1"]},
            ],
        )
        _drain(queue, ["tasks"])

        # Complete and review only A
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "A done")
        _drain(queue, ["completions"])
        service.review_item(children[0].id, "accepted", actor="reviewer")

        # C still pending — needs B too
        assert store.get(children[2].id).status == WorkItemStatus.PENDING


class TestCancelWithRollup:
    def test_cancel_item(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Cancellable")
        _drain(queue, ["plans"])

        service.cancel_item(item.id, actor="coordinator")
        assert store.get(item.id).status == WorkItemStatus.CANCELED

        msgs = queue.consume(["plans"], limit=10)
        assert any(m.payload.get("action") == "canceled" for m in msgs)


class TestMarkReady:
    def test_mark_ready_transitions_pending_to_ready(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Atomic task", actor="coordinator")
        _drain(queue, ["plans"])

        result = service.mark_ready(item.id, actor="planner")

        assert result.status == WorkItemStatus.READY
        assert store.get(item.id).status == WorkItemStatus.READY

        # Should publish to tasks channel
        msgs = queue.consume(["tasks"], limit=10)
        assert len(msgs) == 1
        assert msgs[0].payload["action"] == "ready"
        assert msgs[0].payload["work_item_id"] == item.id

    def test_mark_ready_nonexistent_raises(self):
        service, _, _ = _make_service()
        with pytest.raises(ValueError, match="not found"):
            service.mark_ready("ghost", actor="planner")

    def test_mark_ready_preserves_parent_id(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        _drain(queue, ["plans"])

        # Create a child via decompose with a dependency so it stays pending
        _, children = service.decompose(
            parent.id,
            [{"title": "Dep"}, {"title": "Atomic child", "depends_on": ["$0"]}],
        )
        _drain(queue, ["tasks"])

        # Complete and review the dep to unblock the child
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        service.complete_item(children[0].id, "done")
        _drain(queue, ["completions"])
        service.review_item(children[0].id, "accepted", actor="reviewer")
        _drain(queue, ["tasks"])

        # The child should now be ready with parent_id preserved
        child = store.get(children[1].id)
        assert child.status == WorkItemStatus.READY
        assert child.parent_id == parent.id


class TestBlockUnblock:
    def test_block_and_unblock(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Blockable")
        _drain(queue, ["plans"])

        store.update_status(item.id, WorkItemStatus.READY)
        service.claim_item(item.id, session_id="s1", actor="executor")

        service.block_item(item.id, reason="Waiting for API key")
        assert store.get(item.id).status == WorkItemStatus.BLOCKED
        assert store.get(item.id).context["block_reason"] == "Waiting for API key"

        service.unblock_item(item.id)
        assert store.get(item.id).status == WorkItemStatus.READY
