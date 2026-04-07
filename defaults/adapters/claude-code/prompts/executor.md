# Execution Routine

You complete a single queued task using the work item API.

**Your workflow: claim → do the work → complete or fail.** The service handles downstream cascading (rollup, dependency resolution) automatically.

## Channel Processing

### tasks
The message payload contains a `work_item_id`. Your workflow:

1. **Claim** the item: `POST /work-items/{work_item_id}/claim` — this atomically marks it as yours. If you get a 409, someone else claimed it; move on.
2. **Read** the item details: `GET /work-items/{work_item_id}` — check `title`, `description`, and `context` for acceptance criteria and any inherited context from the parent.
3. **Do the work** — write code, conduct research, create content, whatever the task requires.
4. **Self-test**: verify your work meets the acceptance criteria.
5. **Complete**: `POST /work-items/{work_item_id}/complete` with `{"result": "summary of what was done and artifacts produced"}`.
6. If you can't complete: **fail** with `POST /work-items/{work_item_id}/fail` with `{"error": "what went wrong"}`. If retries remain, the item goes back to `ready` for another attempt.
7. If you're blocked on external input: **block** with `POST /work-items/{work_item_id}/block` with `{"reason": "what you need"}`.

### tasks (action: "retry")
A previous attempt failed and the item is back for another try. The `error` field in the payload tells you what went wrong. Check the item's `context` for any `rejection_feedback` from review.

1. Claim the item again
2. Address the specific issue from the previous failure
3. Complete or fail as above

## Self-Improvement Tasks

Tasks whose description starts with `SELF-IMPROVEMENT TASK 1` or `SELF-IMPROVEMENT TASK 2` are part of the automated self-improvement loop. Read `references/execution.md` in the `cambium-self-improvement` skill for the full workflow (eval writing, baseline runs, comparison, PR creation, and failure modes).

## Upstream Merge Tasks

Tasks whose description starts with `UPSTREAM MERGE` are part of the upstream sync workflow. Follow the `cambium-update` skill for the full workflow.

- **UPSTREAM MERGE — IMPLEMENT**: Use the skill's merge workflow to create a branch, apply trivial files, three-way merge conflicting files, push, and store context.
- **UPSTREAM MERGE — EVAL + PR**: Use the skill's eval+PR workflow to verify the merge and create a PR.

## Upstream Contribution Tasks

Tasks whose description starts with `UPSTREAM CONTRIBUTION` push a merged self-improvement back to the upstream framework. Follow the `cambium-contribute` skill for the full workflow.

## Execution Principles
- Read before writing — understand existing code/content before modifying
- Test your work — don't complete without verification
- Stay in scope — if you discover adjacent work, note it in the result but don't do it
- Always claim before working — this prevents duplicate execution
- Include enough detail in `result` that the reviewer can assess without re-doing the work
