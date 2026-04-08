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
| `external_events` | External triggers (ClickUp, cron, user actions) |
| `plans` | Projects/goals that need decomposition into tasks |
| `tasks` | Concrete tasks ready for execution |
| `completions` | Completed work awaiting review |
| `reviews` | Review verdicts (accepted / rejected / changes_requested) |
| `thoughts` | Observations about patterns and improvements |
| `heartbeat` | Timer-driven wake-up signals for sentry and consolidator |
| `sessions_completed` | Session lifecycle events (system-emitted) |
| `input_needed` | Requests for user input — triggers notification in interlocutor |
| `resume` | Session resume triggers (system-emitted when user answers a request) |

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

### Reviewer publishing a review

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/reviews/publish" \
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

## Updating Session Metadata

To store a watermark or other metadata on a session (e.g., after reflecting on a session transcript):

```bash
curl -s -X PATCH "$CAMBIUM_API_URL/sessions/SESSION_ID/metadata" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"reflected_through_sequence": 42}'
```

Keys are merged into existing metadata — you don't need to include the full metadata object.

## Work Items

Work items are the planning and execution backbone. The coordinator creates them, the planner decomposes them, executors claim and complete them, and the reviewer evaluates them. The service handles channel publishing and rollup automatically — **routines focus on decisions, not plumbing.**

### Creating a work item

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "title": "Research Python testing frameworks",
    "description": "Compare pytest, unittest, and nose2 with recommendation",
    "priority": 5
  }'
```

To assign a work item to the user:
```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "title": "Run setup_oauth.py (requires your credentials)",
    "assigned_to": "user",
    "context": {"delegation": true, "estimated_effort": "10 minutes"}
  }'
```

### Decomposing into children (with dependency references)

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/decompose" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "children": [
      {"title": "Research pytest", "priority": 2},
      {"title": "Research unittest", "priority": 1},
      {"title": "Write comparison", "depends_on": ["$0", "$1"]}
    ]
  }'
```

`$0`, `$1` etc. reference siblings by position — the server resolves them to real IDs. Children with no unmet dependencies are automatically set to `ready` and published to the `tasks` channel.

### Claiming a work item (executor)

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/claim" \
  -H "Authorization: Bearer $CAMBIUM_TOKEN"
```

Returns the claimed item or 409 if someone else got it first. Auth required — identity comes from the JWT.

### Completing a work item

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/complete" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"result": "Comparison written to vault/research/python-testing.md"}'
```

Completing a child triggers automatic rollup — if all siblings are done (or any, for `completion_mode: any`), the parent auto-completes too. Dependencies are also resolved: items waiting on this one become `ready`.

### Failing a work item

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/fail" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"error": "API rate limited, could not complete research"}'
```

If under `max_attempts`, the item goes back to `ready` for retry. Otherwise it's permanently failed and published to `plans` for replanning.

### Reviewing a work item

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/review" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"verdict": "accepted"}'
```

Or reject with feedback:
```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/review" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"verdict": "rejected", "feedback": "Missing comparison of test discovery mechanisms"}'
```

### Blocking / unblocking

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/block" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"reason": "Waiting for API key"}'

curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/unblock" \
  -H "Authorization: Bearer $CAMBIUM_TOKEN"
```

### Updating context

```bash
curl -s -X PATCH "$CAMBIUM_API_URL/work-items/ITEM_ID/context" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"key": "value"}'
```

Keys are merged into existing context.

### Querying

```bash
# Get a single item
curl -s "$CAMBIUM_API_URL/work-items/ITEM_ID"

# Get children
curl -s "$CAMBIUM_API_URL/work-items/ITEM_ID/children"

# Get full subtree
curl -s "$CAMBIUM_API_URL/work-items/ITEM_ID/tree"

# List by status (returns {items: [...], total, limit, truncated})
curl -s "$CAMBIUM_API_URL/work-items?status=ready&limit=50"

# Event history for an item
curl -s "$CAMBIUM_API_URL/work-items/ITEM_ID/events"

# Global event log (for consolidator analysis)
curl -s "$CAMBIUM_API_URL/work-items/events/all?event_type=status_changed&limit=50"
```

### Status lifecycle

```
pending → ready → active → completed
                        → failed (retries if under max_attempts)
                        → blocked → ready
pending/ready/blocked/failed → canceled
```

## Episodic Index

The episodic index tracks routine invocations (episodes) and channel messages (events) as a queryable timeline.

### Querying episodes

```bash
# List recent episodes (since/until required, ISO format)
curl -s "$CAMBIUM_API_URL/episodes?since=2026-04-06T00:00:00Z&until=2026-04-07T00:00:00Z"

# Filter by routine
curl -s "$CAMBIUM_API_URL/episodes?since=2026-04-06T00:00:00Z&until=2026-04-07T00:00:00Z&routine=coordinator"

# Get a specific episode
curl -s "$CAMBIUM_API_URL/episodes/EPISODE_ID"
```

Episode fields: `id`, `session_id`, `routine`, `started_at`, `ended_at`, `status` (running/completed/failed), `trigger_event_ids`, `emitted_event_ids`, `session_acknowledged`, `session_summary`, `summarizer_acknowledged`, `digest_path`.

### Posting a session summary

After completing your work, you can post a 2-3 sentence summary of what you did:

```bash
curl -s -X POST "$CAMBIUM_API_URL/episodes/summary" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"summary": "Analyzed 3 completed sessions. Identified recurring pattern of failed API calls. Published improvement proposal to thoughts channel."}'
```

This uses your JWT to identify the session and marks the episode as self-acknowledged.

### Querying channel events

```bash
# List events in a time range
curl -s "$CAMBIUM_API_URL/events?since=2026-04-06T00:00:00Z&until=2026-04-07T00:00:00Z"

# Filter by channel
curl -s "$CAMBIUM_API_URL/events?since=2026-04-06T00:00:00Z&until=2026-04-07T00:00:00Z&channel=thoughts"

# Get a specific event
curl -s "$CAMBIUM_API_URL/events/EVENT_ID"
```

## Long-term Memory

The system maintains a long-term memory directory as a git-backed markdown repository. Routines read and write files directly via the filesystem.

### Structure

```
~/.cambium/memory/
  _index.md                        # Master MOC (map of content)
  sessions/YYYY-MM-DD/             # Session digests
  digests/{daily,weekly,monthly}/  # Periodic rollups
  knowledge/                       # System's beliefs (wiki)
  library/                         # Digested external content
  .consolidator-state.md           # Processing checkpoints
```

### Knowledge entries

Knowledge files represent the system's beliefs. Every entry must include frontmatter:

```yaml
---
title: Topic description
confidence: 0.85
last_confirmed: 2026-04-06
---
Content of the belief.

**Evidence:**
- Observed in sessions/2026-03-15/sess-abc.md through sessions/2026-04-01/sess-xyz.md
- Confirmed by user (sessions/2026-03-18/sess-def.md)
```

### Library entries

Library files are digested external content (books, papers, etc.). They are reference material, not endorsed as truth. Do not internalize library content as knowledge without independent verification.

### Session digests

Session digests are written by the session-summarizer routine to `sessions/YYYY-MM-DD/{short-session-id}.md`. Each digest captures what happened, what was decided, and what was learned.

## Requests (Human-in-the-Loop)

Agent sessions can request user input via the requests API. There are three types:
- **Permission**: Blocking — session waits for user approval (e.g., "Can I merge PR #17?")
- **Information**: Blocking — session waits for user-provided data (e.g., "What's the API key?")
- **Preference**: Non-blocking — session proceeds with default after timeout (e.g., "Survey or deep-dive?")

### Creating a request

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "type": "permission",
    "summary": "Merge self-improvement PR #17",
    "detail": "Eval passed, 3 files changed.",
    "options": ["approve", "reject"]
  }'
```

For preference requests, include `default` and `timeout_hours`:
```bash
curl -s -X POST "$CAMBIUM_API_URL/requests" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "type": "preference",
    "summary": "Research depth",
    "detail": "Survey or deep-dive?",
    "options": ["survey", "deep-dive"],
    "default": "survey",
    "timeout_hours": 48
  }'
```

### Answering a request (interlocutor only)

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests/REQUEST_ID/answer" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"answer": "approve"}'
```

Only the interlocutor routine can answer requests — other routines get 403.

### Rejecting a request (interlocutor only)

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests/REQUEST_ID/reject" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN"
```

### Querying requests

```bash
# List all pending requests
curl -s "$CAMBIUM_API_URL/requests?status=pending"

# Get a specific request
curl -s "$CAMBIUM_API_URL/requests/REQUEST_ID"

# Get summary counts for monitoring
curl -s "$CAMBIUM_API_URL/requests/summary"
```

### Session resume flow

When a user answers a blocking request:
1. The answer is stored and a `resume` message is published
2. The consumer reopens the originating session with the answer injected
3. The routine picks up where it left off with full conversation context

For blocking requests: create the request, then exit your session cleanly. Do not poll.

## Eval Framework

The eval framework tests changes against staging Cambium instances. Use it for self-improvement tasks.

### Running an eval

```bash
# Basic eval run
.venv/bin/python -m cambium eval <config.yaml> --repo-dir <path>

# Save results as baseline
.venv/bin/python -m cambium eval <config.yaml> --save-baseline baselines/name.json --repo-dir <path>

# Run with config override and compare against baseline
.venv/bin/python -m cambium eval <config.yaml> \
  --config-override <override.yaml> \
  --compare-baseline baselines/name.json \
  --repo-dir <path>

# Override trial count
.venv/bin/python -m cambium eval <config.yaml> --trials 1 --repo-dir <path>

# JSON output
.venv/bin/python -m cambium eval <config.yaml> --output json --repo-dir <path>
```

### Eval config format

```yaml
name: eval-name
trials: 3
timeout: 180

# Optional: override config files in the staging instance
config_override:
  routines/coordinator.yaml:
    batch_window: 5
  adapters/claude-code/prompts/coordinator.md:
    append: "\nNew instruction here"

scenarios:
  - name: scenario-name
    inject:
      channel: external_events
      payload: { goal: "test goal" }
    wait:
      cascade_settled: true    # or: routine_completed: coordinator, timeout_only: true
    assertions:
      - type: episode
        routine: coordinator
        status: completed
      - type: work_item_created
        title_contains: "keyword"
      - type: no_errors
      - type: event_published
        channel: plans
```

### Config override format (for --config-override)

Override files are YAML with file paths as keys:

```yaml
# YAML files: deep-merge keys
routines/coordinator.yaml:
  batch_window: 5

# Markdown files: append, content (full replace), or patch
adapters/claude-code/prompts/coordinator.md:
  append: |
    ## New Section
    New instruction text here.
```

### Canary eval

The canary cascade (`defaults/evals/canary-cascade.yaml`) is a mandatory integration test. Always run it before creating self-improvement PRs to verify the change doesn't break the system.

### Assertion types

| Type | Fields | Description |
|------|--------|-------------|
| `episode` | `routine`, `status` | Check that a routine ran with expected status |
| `work_item_created` | `title_contains` | Check that a work item was created |
| `no_errors` | — | Verify no episodes have error status |
| `event_published` | `channel` | Check that an event was published to a channel |
| `episode_count` | `routine`, `min`, `max` | Check episode count is in range |
| `file_exists` | `path` | Check a file exists in the staging data dir |
| `file_contains` | `path`, `pattern` | Check a file contains a regex pattern |
| `memory_committed` | — | Check that memory git has new commits |
| `llm_rubric` | `target`, `rubric`, `threshold` | LLM-judged quality check |
| `deterministic` | `script`, `threshold` | Run a script, check JSON score |

## Important

- Always publish messages when your routine produces results that should trigger downstream processing.
- Include enough context in the payload that downstream routines can act without re-reading everything.
- For planning and execution, **use the work item API** — the service handles channel publishing and cascading automatically.
- Use `$CAMBIUM_API_URL` and `$CAMBIUM_TOKEN` — never hardcode the URL or token.
