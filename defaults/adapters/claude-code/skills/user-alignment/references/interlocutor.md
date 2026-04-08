# Interlocutor — User Alignment Reference

## Presenting Requests

At session start, query pending requests and user tasks:

```bash
# Pending requests from agent sessions
curl -s "$CAMBIUM_API_URL/requests?status=pending"

# Tasks assigned to the user
curl -s "$CAMBIUM_API_URL/work-items?assigned_to=user&status=ready"
```

Present each pending request with:
- The summary and detail
- The options (if provided)
- The originating routine (created_by field)

## Answering Requests

When the user provides a response:

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests/REQUEST_ID/answer" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"answer": "user response text"}'
```

This triggers the system to resume the originating session with the user's answer.

## Response Paths

For preference requests, the user has three options:
1. **Answer directly** — strongest preference signal
2. **"Use your best judgment"** — explicit delegation; the system proceeds with its default and records this as a preference signal
3. **No response** — the system applies the default after timeout, but this is NOT a preference signal

## Rejecting Requests

If a request is no longer relevant or the user declines:

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests/REQUEST_ID/reject" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN"
```

## Completing User Tasks

When the user has completed a task assigned to them, mark it complete via the normal work item API:

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/ITEM_ID/complete" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{"result": "description of what was done"}'
```

This unblocks any dependent tasks in the plan.
