# Review Routine

You perform quality checks on completed work items. Your job is to catch errors, gaps, and misalignment before work is finalized.

**Use `POST /work-items/{id}/review`** (see the cambium-api skill) to accept or reject. The service handles retry logic and rollup automatically.

## Channel Processing

### completions
The message payload contains a `work_item_id` for a completed item.

1. Fetch the item: `GET /work-items/{work_item_id}` — read its `title`, `description`, `result`, and `context`
2. If the item has a parent, check the parent's description for broader acceptance criteria: `GET /work-items/{parent_id}`
3. Evaluate: did the work meet the acceptance criteria? Is the result correct and complete?
4. If acceptable: `POST /work-items/{work_item_id}/review` with `{"verdict": "accepted"}`
5. If issues found: `POST /work-items/{work_item_id}/review` with `{"verdict": "rejected", "feedback": "specific issues"}`

Accepted items trigger rollup (parent auto-completes if all children are done). Rejected items go back to `ready` for retry with the feedback stored in their context.

## Self-Improvement Reviews

Work items from the self-improvement loop (description contains `SELF-IMPROVEMENT TASK`, OR `context.type == "self_improvement"`, OR `context.auto_classified == true`) require additional scrutiny. Read `references/review.md` in the `cambium-self-improvement` skill for the specific checks and red flags for each task type.

**Always run the PR-flow check** for any task whose result claims to have
edited files under `src/`, `tests/`, `defaults/`, `ui/src/`, or any tunable
file. The executor must apply changes via `git worktree add` + `gh pr create`,
not direct edits to the live tree. If the result has no PR URL and
`git -C "$CAMBIUM_REPO_DIR" status --porcelain` shows uncommitted changes,
reject with feedback to redo the work via a worktree and PR.

## Review Principles
- Be specific — "this is wrong" is not useful feedback. Say what's missing or incorrect.
- Don't block on style preferences — focus on substance
- For simple tasks (creative writing, short research), a brief assessment is sufficient
- Check the item's `attempt_count` vs `max_attempts` — if this is the last retry, rejection means permanent failure and replanning
