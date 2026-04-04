---
name: cambium-api
description: Interact with the Cambium API server to emit events and check queue status
tools:
  - Bash
---

# Cambium API

You are running inside the Cambium event processing system. The Cambium API server is running at `http://127.0.0.1:8350`.

## Emitting Events

When your work produces events that should trigger downstream processing, emit them via the API. Use `curl` to call the endpoint:

```bash
curl -s -X POST http://127.0.0.1:8350/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "EVENT_TYPE", "payload": {...}, "source": "ROUTINE_NAME"}'
```

### Event Types

These are the events you may emit depending on your routine:

| Event | When to emit | Required payload fields |
|-------|-------------|----------------------|
| `goal_needs_plan` | Goal is complex, needs decomposition | `goal`, `context` |
| `task_queued` | A concrete task is ready for execution | `task`, `acceptance_criteria`, `context` |
| `task_completed` | A task has been finished | `task`, `summary`, `artifacts` |
| `task_rejected` | Review found issues with completed work | `task`, `feedback`, `issues` |
| `review_complete` | Review passed, work is accepted | `task`, `assessment` |
| `reflection_needed` | System should evaluate its performance | `trigger`, `context` |
| `feedback_received` | User gave feedback on system behavior | `feedback`, `category` |
| `skill_improvement_proposed` | Reflection identified a skill to improve | `skill`, `proposal`, `evidence` |

### Example: Triage emitting a task

```bash
curl -s -X POST http://127.0.0.1:8350/events \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "task_queued",
    "payload": {
      "task": "Research Python testing frameworks",
      "acceptance_criteria": "Comparison of pytest, unittest, and nose2 with recommendation",
      "context": "User building a small CLI tool, needs fast tests"
    },
    "source": "triage"
  }'
```

### Example: Execution completing a task

```bash
curl -s -X POST http://127.0.0.1:8350/events \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "task_completed",
    "payload": {
      "task": "Research Python testing frameworks",
      "summary": "Compared pytest, unittest, and nose2. Recommending pytest for speed and assertion quality.",
      "artifacts": ["vault/research/python-testing.md"]
    },
    "source": "execution"
  }'
```

## Checking Queue Status

To see what events are pending:

```bash
curl -s http://127.0.0.1:8350/queue/status
```

## Important

- Always emit events when your routine's work produces results that should trigger downstream processing.
- Use your routine name as the `source` field.
- Include enough context in the payload that the downstream routine can act without re-reading everything.
- You may emit multiple events if your work produces multiple outputs (e.g., planning decomposes a goal into several tasks).
