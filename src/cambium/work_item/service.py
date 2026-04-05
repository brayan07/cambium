"""Business logic for work items — rollup, dependency resolution, channel publishing."""

from __future__ import annotations

import logging
from typing import Any

from cambium.models.message import Message
from cambium.queue.base import QueueAdapter
from cambium.work_item.model import (
    CompletionMode,
    RollupMode,
    WorkItem,
    WorkItemStatus,
)
from cambium.work_item.store import WorkItemStore

logger = logging.getLogger(__name__)

_MAX_ROLLUP_DEPTH = 10


class WorkItemService:
    """Wraps WorkItemStore with rollup, dependency resolution, and channel publishing."""

    def __init__(self, store: WorkItemStore, queue: QueueAdapter, preference_service=None) -> None:
        self.store = store
        self.queue = queue
        self.preference_service = preference_service

    # ── public API ───────────────────────────────────────────────────

    def create_item(
        self,
        title: str,
        description: str = "",
        parent_id: str | None = None,
        priority: int = 0,
        completion_mode: CompletionMode = CompletionMode.ALL,
        rollup_mode: RollupMode = RollupMode.AUTO,
        depends_on: list[str] | None = None,
        context: dict[str, Any] | None = None,
        max_attempts: int = 3,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        item = WorkItem.create(
            title=title,
            description=description,
            parent_id=parent_id,
            priority=priority,
            completion_mode=completion_mode,
            rollup_mode=rollup_mode,
            depends_on=depends_on,
            context=context,
            max_attempts=max_attempts,
            actor=actor,
            session_id=session_id,
        )
        self.store.create(item)
        self.queue.publish(Message.create(
            channel="plans",
            payload={"work_item_id": item.id, "action": "created", "title": title},
            source=actor or "system",
        ))
        return item

    def decompose(
        self,
        parent_id: str,
        children_specs: list[dict[str, Any]],
        actor: str | None = None,
        session_id: str | None = None,
    ) -> tuple[WorkItem, list[WorkItem]]:
        """Decompose a parent into children. Resolves $N refs in depends_on."""
        parent = self.store.get(parent_id)
        if parent is None:
            raise ValueError(f"Work item {parent_id} not found")

        # Build children, resolve $N references
        children: list[WorkItem] = []
        for spec in children_specs:
            child = WorkItem.create(
                title=spec["title"],
                description=spec.get("description", ""),
                priority=spec.get("priority", 0),
                depends_on=spec.get("depends_on", []),
                context=spec.get("context", {}),
                max_attempts=spec.get("max_attempts", 3),
                actor=actor,
                session_id=session_id,
            )
            children.append(child)

        # Resolve $N references to real IDs
        self._resolve_dollar_refs(children)

        # Batch-create
        self.store.create_children(parent_id, children, actor=actor, session_id=session_id)

        # Transition children with no unmet dependencies to ready
        for child in children:
            if self._all_deps_completed(child):
                self.store.update_status(
                    child.id, WorkItemStatus.READY, actor=actor, session_id=session_id
                )
                child.status = WorkItemStatus.READY

        # Publish ready children to tasks
        ready_children = [c for c in children if c.status == WorkItemStatus.READY]
        for child in ready_children:
            self.queue.publish(Message.create(
                channel="tasks",
                payload={
                    "work_item_id": child.id,
                    "action": "ready",
                    "title": child.title,
                    "parent_id": parent_id,
                },
                source=actor or "system",
            ))

        return parent, children

    def complete_item(
        self,
        item_id: str,
        result: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        self.store.set_result(item_id, result, actor=actor, session_id=session_id)
        self.store.update_status(
            item_id, WorkItemStatus.COMPLETED, actor=actor, session_id=session_id
        )

        item = self.store.get(item_id)

        # Notify reviewer — rollup and dependency resolution happen on
        # review acceptance, not here. This ensures the reviewer can
        # reject before the parent auto-completes.
        self.queue.publish(Message.create(
            channel="completions",
            payload={
                "work_item_id": item_id,
                "action": "completed",
                "title": item.title,
                "parent_id": item.parent_id,
            },
            source=actor or "system",
        ))

        return item

    def fail_item(
        self,
        item_id: str,
        error: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        self.store.update_status(
            item_id, WorkItemStatus.FAILED, actor=actor, session_id=session_id
        )
        item = self.store.get(item_id)

        if item.attempt_count < item.max_attempts:
            # Retry: back to ready
            self.store.update_status(
                item_id, WorkItemStatus.READY, actor=actor, session_id=session_id
            )
            self.queue.publish(Message.create(
                channel="tasks",
                payload={
                    "work_item_id": item_id,
                    "action": "retry",
                    "error": error,
                    "attempt": item.attempt_count,
                },
                source=actor or "system",
            ))
        else:
            # Permanently failed
            self.queue.publish(Message.create(
                channel="plans",
                payload={
                    "work_item_id": item_id,
                    "action": "failed_permanently",
                    "error": error,
                },
                source=actor or "system",
            ))

        return self.store.get(item_id)

    def review_item(
        self,
        item_id: str,
        verdict: str,
        feedback: str = "",
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        """Review a completed item. verdict: 'accepted' or 'rejected'."""
        if verdict == "accepted":
            # Mark as reviewed, then trigger rollup + dependents
            self.store.set_reviewed(
                item_id, reviewed_by=actor or "reviewer",
                actor=actor, session_id=session_id,
            )
            self._run_rollup(item_id, actor=actor, session_id=session_id)
            self._resolve_dependents(item_id, actor=actor, session_id=session_id)
        elif verdict == "rejected":
            # Move back to failed, then fail_item handles retry logic
            item = self.store.get(item_id)
            if item is None:
                raise ValueError(f"Work item {item_id} not found")
            # Revert to active then fail (completed -> active not allowed, so
            # we record the rejection as an event and re-create as failed)
            self.store.update_context(
                item_id,
                {"rejection_feedback": feedback},
                actor=actor,
                session_id=session_id,
            )
            # Revert to active so fail_item can do active → failed normally
            self._force_status(item_id, WorkItemStatus.ACTIVE, actor, session_id, reason="review_rejection")

            # Process preference signals before returning
            self._process_preference_signals(item_id, verdict, feedback, actor)

            return self.fail_item(item_id, f"Rejected: {feedback}", actor, session_id)
        else:
            raise ValueError(f"Invalid verdict: {verdict}. Use 'accepted' or 'rejected'.")

        # Process preference signals for accepted verdicts
        self._process_preference_signals(item_id, verdict, feedback, actor)

        return self.store.get(item_id)

    def mark_ready(
        self,
        item_id: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        """Transition a pending item directly to ready, skipping decomposition."""
        item = self.store.get(item_id)
        if item is None:
            raise ValueError(f"Work item {item_id} not found")
        self.store.update_status(
            item_id, WorkItemStatus.READY, actor=actor, session_id=session_id
        )
        self.queue.publish(Message.create(
            channel="tasks",
            payload={
                "work_item_id": item_id,
                "action": "ready",
                "title": item.title,
                "parent_id": item.parent_id,
            },
            source=actor or "system",
        ))
        return self.store.get(item_id)

    def claim_item(
        self,
        item_id: str,
        session_id: str,
        actor: str,
    ) -> WorkItem | None:
        claimed = self.store.claim(item_id, session_id=session_id, actor=actor)
        # No channel publish on claim — the event log records it, and publishing
        # to "tasks" would create a spurious executor session for an already-active item.
        return claimed

    def block_item(
        self,
        item_id: str,
        reason: str = "",
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        self.store.update_status(
            item_id, WorkItemStatus.BLOCKED, actor=actor, session_id=session_id
        )
        if reason:
            self.store.update_context(
                item_id, {"block_reason": reason}, actor=actor, session_id=session_id
            )
        self.queue.publish(Message.create(
            channel="plans",
            payload={
                "work_item_id": item_id,
                "action": "blocked",
                "reason": reason,
            },
            source=actor or "system",
        ))
        return self.store.get(item_id)

    def unblock_item(
        self,
        item_id: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        self.store.update_status(
            item_id, WorkItemStatus.READY, actor=actor, session_id=session_id
        )
        self.queue.publish(Message.create(
            channel="tasks",
            payload={"work_item_id": item_id, "action": "unblocked"},
            source=actor or "system",
        ))
        return self.store.get(item_id)

    def cancel_item(
        self,
        item_id: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> WorkItem:
        self.store.update_status(
            item_id, WorkItemStatus.CANCELED, actor=actor, session_id=session_id
        )
        self.queue.publish(Message.create(
            channel="plans",
            payload={"work_item_id": item_id, "action": "canceled"},
            source=actor or "system",
        ))
        return self.store.get(item_id)

    # ── private ──────────────────────────────────────────────────────

    def _resolve_dollar_refs(self, children: list[WorkItem]) -> None:
        """Replace $0, $1, etc. in depends_on with real child IDs."""
        for child in children:
            resolved = []
            for dep in child.depends_on:
                if isinstance(dep, str) and dep.startswith("$"):
                    try:
                        idx = int(dep[1:])
                        resolved.append(children[idx].id)
                    except (ValueError, IndexError):
                        raise ValueError(f"Invalid $N reference: {dep}")
                else:
                    resolved.append(dep)
            child.depends_on = resolved

    def _all_deps_completed(self, item: WorkItem) -> bool:
        """Check if all dependencies are completed and reviewed."""
        for dep_id in item.depends_on:
            dep = self.store.get(dep_id)
            if dep is None or dep.status != WorkItemStatus.COMPLETED:
                return False
            if dep.reviewed_by is None:
                return False
        return True

    def _run_rollup(
        self,
        child_id: str,
        actor: str | None = None,
        session_id: str | None = None,
        depth: int = 0,
    ) -> None:
        """Check if completing this child should complete the parent."""
        if depth >= _MAX_ROLLUP_DEPTH:
            logger.warning("Rollup depth limit reached at item %s", child_id)
            return

        child = self.store.get(child_id)
        if child is None or child.parent_id is None:
            return

        parent = self.store.get(child.parent_id)
        if parent is None or parent.status in (
            WorkItemStatus.COMPLETED,
            WorkItemStatus.CANCELED,
        ):
            return

        children = self.store.get_children(parent.id)
        # For auto-rollup, children must be both completed AND reviewed.
        # For synthesize, we just need completion to trigger the synthesis request.
        reviewed = [
            c for c in children
            if c.status == WorkItemStatus.COMPLETED and c.reviewed_by is not None
        ]
        completed = [c for c in children if c.status == WorkItemStatus.COMPLETED]

        if parent.rollup_mode == RollupMode.AUTO:
            # Auto-rollup requires reviewed children — trust propagates upward
            should_complete = False
            if parent.completion_mode == CompletionMode.ALL:
                should_complete = len(reviewed) == len(children)
            elif parent.completion_mode == CompletionMode.ANY:
                should_complete = len(reviewed) >= 1

            if not should_complete:
                return

            results = [c.result or "" for c in reviewed]
            combined = "; ".join(r for r in results if r)
            self.store.set_result(
                parent.id, combined, actor=actor, session_id=session_id
            )
            self._force_status(
                parent.id, WorkItemStatus.COMPLETED, actor=actor, session_id=session_id,
                reason="auto_rollup",
            )
            # Auto-rollup parents inherit review trust from their children
            self.store.set_reviewed(
                parent.id, reviewed_by="auto_rollup",
                actor=actor, session_id=session_id,
            )
            # No publish to plans — auto_completed parents need no planning.
            # The status change is already recorded in the event log.
            # Recurse up
            self._run_rollup(
                parent.id, actor=actor, session_id=session_id, depth=depth + 1
            )
        elif parent.rollup_mode == RollupMode.SYNTHESIZE:
            # Synthesize triggers on completion (not review) — the synthesis
            # result itself will need review before the parent is considered done.
            should_synthesize = False
            if parent.completion_mode == CompletionMode.ALL:
                should_synthesize = len(completed) == len(children)
            elif parent.completion_mode == CompletionMode.ANY:
                should_synthesize = len(completed) >= 1

            if not should_synthesize:
                return

            self.queue.publish(Message.create(
                channel="plans",
                payload={
                    "work_item_id": parent.id,
                    "action": "synthesize",
                    "completed_children": [c.id for c in completed],
                },
                source=actor or "system",
            ))

    def _resolve_dependents(
        self,
        completed_id: str,
        actor: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Find items that depend on completed_id and make them ready if all deps are met."""
        dependents = self.store.get_dependents(completed_id)
        for dep in dependents:
            if dep.status != WorkItemStatus.PENDING:
                continue
            if self._all_deps_completed(dep):
                self.store.update_status(
                    dep.id, WorkItemStatus.READY, actor=actor, session_id=session_id
                )
                self.queue.publish(Message.create(
                    channel="tasks",
                    payload={
                        "work_item_id": dep.id,
                        "action": "ready",
                        "title": dep.title,
                        "unblocked_by": completed_id,
                    },
                    source=actor or "system",
                ))

    def _force_status(
        self,
        item_id: str,
        status: WorkItemStatus,
        actor: str | None = None,
        session_id: str | None = None,
        reason: str = "unspecified",
    ) -> None:
        """Bypass state machine for special cases (rollup, review rejection)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        self.store._conn.execute(
            "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, item_id),
        )
        self.store._conn.commit()
        # Still emit event for auditability
        cur = self.store._conn.cursor()
        self.store._emit_event(
            cur,
            item_id,
            "status_forced",
            data={"to": status.value, "reason": reason},
            actor=actor,
            session_id=session_id,
        )
        self.store._conn.commit()

    def _process_preference_signals(
        self,
        item_id: str,
        verdict: str,
        feedback: str,
        actor: str | None,
    ) -> None:
        """Extract preference signals from a review and publish for case generation."""
        if self.preference_service is None:
            return
        item = self.store.get(item_id)
        if item is None:
            return
        try:
            self.preference_service.process_review(item, verdict, feedback, actor)
        except Exception:
            logger.exception("Failed to process preference signals for %s", item_id)

        # Publish for async case generation by consolidator
        self.queue.publish(Message.create(
            channel="preference_updates",
            payload={
                "work_item_id": item_id,
                "action": "review_processed",
                "verdict": verdict,
                "feedback": feedback,
            },
            source=actor or "system",
        ))
