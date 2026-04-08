# Executor — User Alignment Reference

## When to Create Requests

Create a request when you hit a gate that requires user involvement:

| Situation | Request type | Example |
|---|---|---|
| Need permission for a risky action | `permission` | Merging a PR, deleting data |
| Need information only the user has | `information` | API keys, credentials, business context |
| Choosing between approaches | `preference` | Research depth, output format |

## Creating a Blocking Request

For permission and information requests:

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "type": "permission",
    "summary": "Merge self-improvement PR #17",
    "detail": "Eval passed (100%), 3 files changed. Changes: updated coordinator prompt, added new skill.",
    "options": ["approve", "reject"]
  }'
```

## After Creating a Blocking Request

1. Complete any cleanup (save partial work, update context on the work item)
2. **Exit your session cleanly** — do not wait or poll for an answer
3. The system automatically resumes your session when the user responds
4. On resume, you'll receive the user's answer as a message in your conversation

## Important

- Permission and information requests **never expire** — they wait until the user responds
- Preference requests have a default and timeout — they expire automatically
- Block the work item if you can't proceed: `POST /work-items/ITEM_ID/block`

## Preference-Aware Execution

Before making implementation choices (code style, tool selection, output format),
check for relevant preference beliefs in `$CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/`.

Follow high-confidence preferences (≥ 0.7) without asking. For lower-confidence preferences,
use your judgment but note the preference in your session summary.
