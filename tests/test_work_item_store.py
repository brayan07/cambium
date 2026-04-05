"""Tests for work item store."""

import pytest

from cambium.work_item.model import (
    CompletionMode,
    RollupMode,
    WorkItem,
    WorkItemStatus,
)
from cambium.work_item.store import WorkItemStore


class TestCreate:
    def test_create_and_get(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Build feature", description="Do the thing")
        store.create(item)
        got = store.get(item.id)
        assert got is not None
        assert got.id == item.id
        assert got.title == "Build feature"
        assert got.description == "Do the thing"
        assert got.status == WorkItemStatus.PENDING
        assert got.depends_on == []
        assert got.context == {}
        assert got.attempt_count == 0

    def test_create_with_all_fields(self):
        store = WorkItemStore()
        item = WorkItem.create(
            title="Sub-task",
            description="Details",
            priority=5,
            completion_mode=CompletionMode.ANY,
            rollup_mode=RollupMode.SYNTHESIZE,
            depends_on=["dep-1"],
            context={"key": "value"},
            max_attempts=5,
            actor="planner",
            session_id="sess-1",
        )
        store.create(item)
        got = store.get(item.id)
        assert got.priority == 5
        assert got.completion_mode == CompletionMode.ANY
        assert got.rollup_mode == RollupMode.SYNTHESIZE
        assert got.depends_on == ["dep-1"]
        assert got.context == {"key": "value"}
        assert got.max_attempts == 5
        assert got.actor == "planner"
        assert got.session_id == "sess-1"

    def test_get_missing_returns_none(self):
        store = WorkItemStore()
        assert store.get("nonexistent") is None

    def test_create_emits_event(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Test")
        store.create(item)
        events = store.get_events(item_id=item.id)
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].data["title"] == "Test"


class TestHierarchy:
    def test_get_children(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Parent")
        store.create(parent)
        c1 = WorkItem.create(title="Child 1", parent_id=parent.id, priority=1)
        c2 = WorkItem.create(title="Child 2", parent_id=parent.id, priority=2)
        store.create(c1)
        store.create(c2)

        children = store.get_children(parent.id)
        assert len(children) == 2
        assert children[0].title == "Child 2"  # higher priority first
        assert children[1].title == "Child 1"

    def test_get_subtree(self):
        store = WorkItemStore()
        root = WorkItem.create(title="Root")
        store.create(root)
        child = WorkItem.create(title="Child", parent_id=root.id)
        store.create(child)
        grandchild = WorkItem.create(title="Grandchild", parent_id=child.id)
        store.create(grandchild)

        subtree = store.get_subtree(root.id)
        assert len(subtree) == 2
        ids = {i.id for i in subtree}
        assert child.id in ids
        assert grandchild.id in ids
        assert root.id not in ids

    def test_get_children_empty(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Leaf")
        store.create(parent)
        assert store.get_children(parent.id) == []


class TestStatusMachine:
    def test_valid_transitions(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)

        store.update_status(item.id, WorkItemStatus.READY)
        assert store.get(item.id).status == WorkItemStatus.READY

        store.update_status(item.id, WorkItemStatus.ACTIVE)
        assert store.get(item.id).status == WorkItemStatus.ACTIVE

        store.update_status(item.id, WorkItemStatus.COMPLETED)
        assert store.get(item.id).status == WorkItemStatus.COMPLETED

    def test_invalid_transition_raises(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)

        with pytest.raises(ValueError, match="Invalid transition"):
            store.update_status(item.id, WorkItemStatus.COMPLETED)

    def test_completed_is_terminal(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)
        store.update_status(item.id, WorkItemStatus.ACTIVE)
        store.update_status(item.id, WorkItemStatus.COMPLETED)

        with pytest.raises(ValueError, match="Invalid transition"):
            store.update_status(item.id, WorkItemStatus.READY)

    def test_canceled_is_terminal(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.CANCELED)

        with pytest.raises(ValueError, match="Invalid transition"):
            store.update_status(item.id, WorkItemStatus.READY)

    def test_failed_to_ready_increments_attempt(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task", max_attempts=3)
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)

        # First attempt
        store.update_status(item.id, WorkItemStatus.ACTIVE)
        assert store.get(item.id).attempt_count == 1
        store.update_status(item.id, WorkItemStatus.FAILED)

        # Retry
        store.update_status(item.id, WorkItemStatus.READY)
        store.update_status(item.id, WorkItemStatus.ACTIVE)
        assert store.get(item.id).attempt_count == 2

    def test_failed_max_attempts_blocks_retry(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task", max_attempts=1)
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)
        store.update_status(item.id, WorkItemStatus.ACTIVE)
        store.update_status(item.id, WorkItemStatus.FAILED)

        with pytest.raises(ValueError, match="Max attempts"):
            store.update_status(item.id, WorkItemStatus.READY)

    def test_blocked_to_ready(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)
        store.update_status(item.id, WorkItemStatus.ACTIVE)
        store.update_status(item.id, WorkItemStatus.BLOCKED)
        store.update_status(item.id, WorkItemStatus.READY)
        assert store.get(item.id).status == WorkItemStatus.READY

    def test_status_change_emits_event(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY, actor="planner")

        events = store.get_events(item_id=item.id, event_type="status_changed")
        assert len(events) == 1
        assert events[0].data["from"] == "pending"
        assert events[0].data["to"] == "ready"
        assert events[0].actor == "planner"

    def test_nonexistent_item_raises(self):
        store = WorkItemStore()
        with pytest.raises(ValueError, match="not found"):
            store.update_status("ghost", WorkItemStatus.READY)


class TestClaim:
    def test_claim_ready_item(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)

        claimed = store.claim(item.id, session_id="sess-1", actor="executor")
        assert claimed is not None
        assert claimed.status == WorkItemStatus.ACTIVE
        assert claimed.actor == "executor"
        assert claimed.session_id == "sess-1"
        assert claimed.attempt_count == 1

    def test_claim_non_ready_returns_none(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        # Still pending, not ready
        result = store.claim(item.id, session_id="s", actor="a")
        assert result is None

    def test_claim_emits_event(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)
        store.claim(item.id, session_id="s1", actor="executor")

        events = store.get_events(item_id=item.id, event_type="claimed")
        assert len(events) == 1
        assert events[0].data["actor"] == "executor"


class TestDependencies:
    def test_add_and_get_dependents(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        store.create(a)
        store.create(b)

        store.add_dependency(b.id, a.id)
        got = store.get(b.id)
        assert a.id in got.depends_on

        dependents = store.get_dependents(a.id)
        assert len(dependents) == 1
        assert dependents[0].id == b.id

    def test_remove_dependency(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        store.create(a)
        store.create(b)

        store.add_dependency(b.id, a.id)
        store.remove_dependency(b.id, a.id)
        got = store.get(b.id)
        assert got.depends_on == []

    def test_cycle_detection(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        c = WorkItem.create(title="C")
        store.create(a)
        store.create(b)
        store.create(c)

        store.add_dependency(b.id, a.id)  # B depends on A
        store.add_dependency(c.id, b.id)  # C depends on B

        with pytest.raises(ValueError, match="cycle"):
            store.add_dependency(a.id, c.id)  # A depends on C → cycle

    def test_self_dependency_is_cycle(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        store.create(a)

        with pytest.raises(ValueError, match="cycle"):
            store.add_dependency(a.id, a.id)

    def test_duplicate_dependency_is_noop(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        store.create(a)
        store.create(b)

        store.add_dependency(b.id, a.id)
        store.add_dependency(b.id, a.id)  # duplicate — no error
        got = store.get(b.id)
        assert got.depends_on == [a.id]

    def test_dependency_events(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        store.create(a)
        store.create(b)

        store.add_dependency(b.id, a.id)
        events = store.get_events(item_id=b.id, event_type="dependency_added")
        assert len(events) == 1

        store.remove_dependency(b.id, a.id)
        events = store.get_events(item_id=b.id, event_type="dependency_removed")
        assert len(events) == 1


class TestListReady:
    def test_list_ready_excludes_parents(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Parent")
        store.create(parent)
        store.update_status(parent.id, WorkItemStatus.READY)

        child = WorkItem.create(title="Child", parent_id=parent.id)
        store.create(child)
        store.update_status(child.id, WorkItemStatus.READY)

        ready = store.list_ready()
        assert len(ready) == 1
        assert ready[0].id == child.id  # parent excluded — has children

    def test_list_ready_ordered_by_priority(self):
        store = WorkItemStore()
        low = WorkItem.create(title="Low", priority=1)
        high = WorkItem.create(title="High", priority=10)
        store.create(low)
        store.create(high)
        store.update_status(low.id, WorkItemStatus.READY)
        store.update_status(high.id, WorkItemStatus.READY)

        ready = store.list_ready()
        assert ready[0].title == "High"
        assert ready[1].title == "Low"

    def test_list_ready_limit(self):
        store = WorkItemStore()
        for i in range(5):
            item = WorkItem.create(title=f"Item {i}")
            store.create(item)
            store.update_status(item.id, WorkItemStatus.READY)
        assert len(store.list_ready(limit=2)) == 2


class TestContext:
    def test_update_context_merges(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task", context={"a": 1})
        store.create(item)

        store.update_context(item.id, {"b": 2})
        got = store.get(item.id)
        assert got.context == {"a": 1, "b": 2}

    def test_update_context_overwrites_key(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task", context={"a": 1})
        store.create(item)

        store.update_context(item.id, {"a": 99})
        got = store.get(item.id)
        assert got.context["a"] == 99

    def test_update_context_nonexistent_is_noop(self):
        store = WorkItemStore()
        store.update_context("ghost", {"key": "val"})  # no error

    def test_update_context_emits_event(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_context(item.id, {"foo": "bar"}, actor="planner")

        events = store.get_events(item_id=item.id, event_type="context_updated")
        assert len(events) == 1
        assert events[0].data["merged_keys"] == ["foo"]


class TestResult:
    def test_set_result(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)

        store.set_result(item.id, "The answer is 42")
        got = store.get(item.id)
        assert got.result == "The answer is 42"

    def test_set_result_emits_event(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.set_result(item.id, "done", actor="executor")

        events = store.get_events(item_id=item.id, event_type="result_set")
        assert len(events) == 1
        assert events[0].data["result"] == "done"


class TestReparent:
    def test_reparent(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        child = WorkItem.create(title="Child", parent_id=a.id)
        store.create(a)
        store.create(b)
        store.create(child)

        store.reparent(child.id, b.id)
        got = store.get(child.id)
        assert got.parent_id == b.id
        assert store.get_children(a.id) == []
        assert len(store.get_children(b.id)) == 1

    def test_reparent_to_none(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Parent")
        child = WorkItem.create(title="Child", parent_id=parent.id)
        store.create(parent)
        store.create(child)

        store.reparent(child.id, None)
        got = store.get(child.id)
        assert got.parent_id is None

    def test_reparent_emits_event(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        child = WorkItem.create(title="Child", parent_id=a.id)
        store.create(a)
        store.create(child)
        store.reparent(child.id, None)

        events = store.get_events(item_id=child.id, event_type="reparented")
        assert len(events) == 1
        assert events[0].data["from_parent"] == a.id
        assert events[0].data["to_parent"] is None

    def test_reparent_nonexistent_raises(self):
        store = WorkItemStore()
        with pytest.raises(ValueError, match="not found"):
            store.reparent("ghost", None)


class TestCreateChildren:
    def test_batch_create(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Parent")
        store.create(parent)

        children = [
            WorkItem.create(title="C1", priority=1),
            WorkItem.create(title="C2", priority=2),
        ]
        store.create_children(parent.id, children, actor="planner")

        got = store.get_children(parent.id)
        assert len(got) == 2
        assert all(c.parent_id == parent.id for c in got)

    def test_batch_create_emits_events(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Parent")
        store.create(parent)

        children = [WorkItem.create(title="C1")]
        store.create_children(parent.id, children)

        # Child creation event + parent's children_created event
        child_events = store.get_events(item_id=children[0].id)
        assert any(e.event_type == "created" for e in child_events)

        parent_events = store.get_events(item_id=parent.id, event_type="children_created")
        assert len(parent_events) == 1
        assert children[0].id in parent_events[0].data["child_ids"]

    def test_batch_create_nonexistent_parent_raises(self):
        store = WorkItemStore()
        with pytest.raises(ValueError, match="not found"):
            store.create_children("ghost", [WorkItem.create(title="C")])


class TestEventLog:
    def test_events_ordered_by_time(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)
        store.update_status(item.id, WorkItemStatus.ACTIVE)

        events = store.get_events(item_id=item.id)
        assert len(events) == 3  # created + 2 status changes
        types = [e.event_type for e in events]
        assert types == ["created", "status_changed", "status_changed"]

    def test_filter_by_event_type(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        store.update_status(item.id, WorkItemStatus.READY)

        events = store.get_events(item_id=item.id, event_type="created")
        assert len(events) == 1

    def test_filter_by_after(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)

        first_event = store.get_events(item_id=item.id)[0]
        store.update_status(item.id, WorkItemStatus.READY)

        events = store.get_events(item_id=item.id, after=first_event.created_at)
        assert len(events) == 1
        assert events[0].event_type == "status_changed"

    def test_global_events_query(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        store.create(a)
        store.create(b)

        all_events = store.get_events()
        assert len(all_events) == 2  # both creation events

    def test_events_limit(self):
        store = WorkItemStore()
        item = WorkItem.create(title="Task")
        store.create(item)
        for _ in range(5):
            store.update_context(item.id, {"tick": True})

        events = store.get_events(item_id=item.id, limit=3)
        assert len(events) == 3


class TestListItems:
    def test_list_by_status(self):
        store = WorkItemStore()
        a = WorkItem.create(title="A")
        b = WorkItem.create(title="B")
        store.create(a)
        store.create(b)
        store.update_status(a.id, WorkItemStatus.READY)

        ready = store.list_items(status=WorkItemStatus.READY)
        assert len(ready) == 1
        assert ready[0].id == a.id

    def test_list_by_parent(self):
        store = WorkItemStore()
        parent = WorkItem.create(title="Parent")
        child = WorkItem.create(title="Child", parent_id=parent.id)
        orphan = WorkItem.create(title="Orphan")
        store.create(parent)
        store.create(child)
        store.create(orphan)

        children = store.list_items(parent_id=parent.id)
        assert len(children) == 1
        assert children[0].id == child.id

    def test_list_limit(self):
        store = WorkItemStore()
        for i in range(10):
            store.create(WorkItem.create(title=f"Item {i}"))
        assert len(store.list_items(limit=3)) == 3
