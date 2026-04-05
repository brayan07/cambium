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

## Execution Principles
- Read before writing — understand existing code/content before modifying
- Test your work — don't complete without verification
- Stay in scope — if you discover adjacent work, note it in the result but don't do it
- Always claim before working — this prevents duplicate execution
- Include enough detail in `result` that the reviewer can assess without re-doing the work
