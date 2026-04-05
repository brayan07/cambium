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
        queue.consume(["plans"], limit=10)  # drain creation message

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
        queue.consume(["plans"], limit=10)

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
        queue.consume(["plans"], limit=10)

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
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(
            parent.id, [{"title": "A"}, {"title": "B"}]
        )
        queue.consume(["tasks"], limit=10)

        # Claim and complete first child — parent should NOT complete yet
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[0].id, "done A")
        assert store.get(parent.id).status != WorkItemStatus.COMPLETED

        # Claim and complete second child — parent should auto-complete
        service.claim_item(children[1].id, session_id="s2", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[1].id, "done B")
        p = store.get(parent.id)
        assert p.status == WorkItemStatus.COMPLETED
        assert "done A" in p.result
        assert "done B" in p.result

    def test_recursive_rollup(self):
        service, store, queue = _make_service()
        root = service.create_item(title="Root")
        queue.consume(["plans"], limit=10)

        _, mid = service.decompose(root.id, [{"title": "Mid"}])
        queue.consume(["tasks"], limit=10)
        # Mid is now ready — make it pending again so we can decompose it
        # Actually, mid is ready and has no children. Let's decompose it directly.
        # To decompose, we need to claim it first (or it's ready).
        # Actually, decompose doesn't care about status — it just adds children.
        _, leaves = service.decompose(mid[0].id, [{"title": "Leaf"}])
        queue.consume(["tasks"], limit=10)

        service.claim_item(leaves[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(leaves[0].id, "leaf done")

        # Mid should auto-complete
        assert store.get(mid[0].id).status == WorkItemStatus.COMPLETED
        # Root should auto-complete
        assert store.get(root.id).status == WorkItemStatus.COMPLETED


class TestRollupAny:
    def test_any_mode_completes_on_first_child(self):
        service, store, queue = _make_service()
        parent = service.create_item(
            title="Race", completion_mode=CompletionMode.ANY
        )
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(
            parent.id, [{"title": "A"}, {"title": "B"}]
        )
        queue.consume(["tasks"], limit=10)

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[0].id, "A wins")
        assert store.get(parent.id).status == WorkItemStatus.COMPLETED


class TestSynthesizeRollup:
    def test_synthesize_publishes_to_plans(self):
        service, store, queue = _make_service()
        parent = service.create_item(
            title="Synthesize parent",
            rollup_mode=RollupMode.SYNTHESIZE,
        )
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(parent.id, [{"title": "Only child"}])
        queue.consume(["tasks"], limit=10)

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[0].id, "child result")

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
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(
            parent.id, [{"title": "Retry task", "max_attempts": 3}]
        )
        queue.consume(["tasks"], limit=10)

        # Claim and fail
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
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
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(
            parent.id, [{"title": "Fragile", "max_attempts": 1}]
        )
        queue.consume(["tasks"], limit=10)

        # Claim (increments attempt_count to 1 = max_attempts)
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)

        result = service.fail_item(children[0].id, "dead", actor="executor")
        assert result.status == WorkItemStatus.FAILED

        # Should publish failed_permanently to plans
        msgs = queue.consume(["plans"], limit=10)
        assert any(m.payload.get("action") == "failed_permanently" for m in msgs)


class TestReview:
    def test_accepted_triggers_rollup(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Reviewable")
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(parent.id, [{"title": "Child"}])
        queue.consume(["tasks"], limit=10)

        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[0].id, "done")

        # Parent auto-completed (rollup already ran in complete_item)
        assert store.get(parent.id).status == WorkItemStatus.COMPLETED

    def test_rejected_retries(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Review me", max_attempts=3)
        queue.consume(["plans"], limit=10)

        # Move to ready, claim, complete
        store.update_status(item.id, WorkItemStatus.READY)
        service.claim_item(item.id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(item.id, "first attempt")

        # Reject — should go back to ready
        result = service.review_item(
            item.id, verdict="rejected", feedback="Not good enough"
        )
        assert result.status == WorkItemStatus.READY

        # Context should have rejection feedback
        got = store.get(item.id)
        assert got.context["rejection_feedback"] == "Not good enough"

    def test_invalid_verdict_raises(self):
        service, _, queue = _make_service()
        item = service.create_item(title="Item")
        queue.consume(["plans"], limit=10)

        with pytest.raises(ValueError, match="Invalid verdict"):
            service.review_item(item.id, verdict="maybe")


class TestDependencyResolution:
    def test_completing_dep_unblocks_dependent(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(
            parent.id,
            [
                {"title": "Dep"},
                {"title": "Dependent", "depends_on": ["$0"]},
            ],
        )
        queue.consume(["tasks"], limit=10)

        # Dependent should be pending
        assert store.get(children[1].id).status == WorkItemStatus.PENDING

        # Claim and complete the dependency
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[0].id, "dep done")

        # Dependent should now be ready
        assert store.get(children[1].id).status == WorkItemStatus.READY

    def test_partial_deps_stay_pending(self):
        service, store, queue = _make_service()
        parent = service.create_item(title="Parent")
        queue.consume(["plans"], limit=10)

        _, children = service.decompose(
            parent.id,
            [
                {"title": "A"},
                {"title": "B"},
                {"title": "C", "depends_on": ["$0", "$1"]},
            ],
        )
        queue.consume(["tasks"], limit=10)

        # Complete only A
        service.claim_item(children[0].id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)
        service.complete_item(children[0].id, "A done")

        # C still pending — needs B too
        assert store.get(children[2].id).status == WorkItemStatus.PENDING


class TestCancelWithRollup:
    def test_cancel_item(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Cancellable")
        queue.consume(["plans"], limit=10)

        service.cancel_item(item.id, actor="coordinator")
        assert store.get(item.id).status == WorkItemStatus.CANCELED

        msgs = queue.consume(["plans"], limit=10)
        assert any(m.payload.get("action") == "canceled" for m in msgs)


class TestBlockUnblock:
    def test_block_and_unblock(self):
        service, store, queue = _make_service()
        item = service.create_item(title="Blockable")
        queue.consume(["plans"], limit=10)

        store.update_status(item.id, WorkItemStatus.READY)
        service.claim_item(item.id, session_id="s1", actor="executor")
        queue.consume(["tasks"], limit=10)

        service.block_item(item.id, reason="Waiting for API key")
        assert store.get(item.id).status == WorkItemStatus.BLOCKED
        assert store.get(item.id).context["block_reason"] == "Waiting for API key"

        service.unblock_item(item.id)
        assert store.get(item.id).status == WorkItemStatus.READY
