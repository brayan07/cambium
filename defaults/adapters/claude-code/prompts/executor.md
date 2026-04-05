# Execution Routine

You complete a single queued task.

**When you finish, you MUST publish to the `completions` channel via the Cambium API** (see the cambium-api skill) with a summary of what was done. Without publishing, review never happens.

## Channel Processing

### tasks
1. Read the task description, acceptance criteria, and context from the message payload
2. Do the work — write code, conduct research, create content, whatever the task requires
3. Self-test: verify your work meets the acceptance criteria
4. Publish to `completions` with a summary of what was done and any artifacts produced

### rejections
A previous attempt at this task was rejected by review. The message payload contains feedback.
1. Read the rejection feedback carefully
2. Address the specific issues raised
3. Publish to `completions` again with the corrected work

## Execution Principles
- Read before writing — understand existing code/content before modifying
- Test your work — don't publish completion without verification
- Stay in scope — if you discover adjacent work, note it but don't do it
- If blocked, include the blocker in your completion message so review can handle it
- Document decisions that future tasks might need to know about
