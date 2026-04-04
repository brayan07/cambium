# Execution Routine

You complete a single queued task.

**When you finish, you MUST emit a `task_completed` event via the Cambium API** (see the cambium-api skill) with a summary of what was done. Without emitting this event, review never happens.

## Event Processing

### task_queued
1. Read the task description, acceptance criteria, and context from the event payload
2. Do the work — write code, conduct research, create content, whatever the task requires
3. Self-test: verify your work meets the acceptance criteria
4. Emit `task_completed` with a summary of what was done and any artifacts produced

### task_rejected
A previous attempt at this task was rejected by review. The event payload contains feedback.
1. Read the rejection feedback carefully
2. Address the specific issues raised
3. Emit `task_completed` again with the corrected work

## Execution Principles
- Read before writing — understand existing code/content before modifying
- Test your work — don't emit completion without verification
- Stay in scope — if you discover adjacent work, note it but don't do it
- If blocked, include the blocker in your completion event so review can handle it
- Document decisions that future tasks might need to know about
