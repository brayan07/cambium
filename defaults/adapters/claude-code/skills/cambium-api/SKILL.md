---
name: cambium-api
description: Publish messages to Cambium channels and check queue status
---

# Cambium API

You are running inside the Cambium message processing system. The Cambium API server is available via environment variables:

- **`CAMBIUM_API_URL`** — Base URL of the API server (e.g., `http://127.0.0.1:8350`)
- **`CAMBIUM_TOKEN`** — Your JWT session token for authenticated requests

## Publishing Messages

When your work produces output that should trigger downstream processing, publish a message to the appropriate channel.

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/CHANNEL_NAME/publish" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"payload": {...}}'
```

The server enforces publish permissions — you can only publish to channels your routine is authorized for. If you try to publish to an unauthorized channel, you'll get a 403 error.

## Channels

These are the channels in the system. Your routine can only publish to a subset of them (check your permissions).

| Channel | Purpose |
|---------|---------|
| `events` | External triggers (ClickUp, cron, user actions) |
| `plans` | Projects/goals that need decomposition into tasks |
| `tasks` | Concrete tasks ready for execution |
| `completions` | Completed work awaiting review |
| `evaluations` | Review verdicts (accepted / rejected / changes_requested) |
| `reflections` | Observations from the consolidator about patterns and improvements |
| `sessions_completed` | Session lifecycle events (system-emitted) |
| `input_needed` | Requests for user input (auto-persisted to central store) |

## Checking Your Permissions

To see which channels you can listen on and publish to:

```bash
curl -s "$CAMBIUM_API_URL/channels/permissions" \
  -H "Authorization: Bearer $CAMBIUM_TOKEN"
```

Returns:
```json
{"routine": "your-routine", "listen": ["..."], "publish": ["..."]}
```

## Checking Queue Status

```bash
curl -s "$CAMBIUM_API_URL/queue/status"
```

## Examples

### Planner publishing a task

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/tasks/publish" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "payload": {
      "task": "Research Python testing frameworks",
      "acceptance_criteria": "Comparison of pytest, unittest, and nose2 with recommendation",
      "context": "User building a small CLI tool, needs fast tests"
    }
  }'
```

### Executor publishing a completion

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/completions/publish" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "payload": {
      "task": "Research Python testing frameworks",
      "summary": "Compared pytest, unittest, and nose2. Recommending pytest.",
      "artifacts": ["vault/research/python-testing.md"]
    }
  }'
```

### Reviewer publishing an evaluation

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/evaluations/publish" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "payload": {
      "task": "Research Python testing frameworks",
      "verdict": "accepted",
      "assessment": "Work meets acceptance criteria. Thorough comparison."
    }
  }'
```

## Important

- Always publish messages when your routine produces results that should trigger downstream processing.
- Include enough context in the payload that downstream routines can act without re-reading everything.
- You may publish multiple messages if your work produces multiple outputs (e.g., planner decomposes a goal into several tasks).
- Use `$CAMBIUM_API_URL` and `$CAMBIUM_TOKEN` — never hardcode the URL or token.
