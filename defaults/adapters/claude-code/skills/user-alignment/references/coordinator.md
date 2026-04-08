# Coordinator — User Alignment Reference

## Queue Monitoring

On each activation, check the user's queue:

```bash
# Request summary — counts by type and status
curl -s "$CAMBIUM_API_URL/requests/summary"

# User tasks
curl -s "$CAMBIUM_API_URL/work-items?assigned_to=user"
```

## Overload Detection

If the user has many pending items:
- **Preference requests past timeout**: these expire automatically — no action needed
- **Multiple blocking requests**: the user may be a bottleneck; note this when creating work items
- **Many user tasks**: consider publishing to `plans` requesting the planner find approaches that don't require user input

## When NOT to Create Requests

Before creating a new work item that would require user input, check if:
- A similar request is already pending
- The information might be available in the memory system
- A reasonable default exists that would let the system proceed

## Preference-Aware Coordination

When routing work or setting priorities, check preference beliefs for relevant
signals about the user's preferred working patterns (e.g., bundled vs. split PRs,
async vs. interactive work, notification frequency):

```bash
grep -rl "relevant-keyword" $CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/
```

## Attention Budget Awareness

The attention budget belief at `knowledge/user/preferences/attention-budget.md`
tells you how much user bandwidth is typically available. Read it on each activation.

- If the belief exists with confidence >= 0.7, use its daily tolerance as the
  overload threshold
- If the belief does not exist or confidence is low, default to 5 pending requests
- When in overload mode, include "User queue at capacity" in work item descriptions
  so the planner knows to prefer autonomous approaches
- Exit overload mode when pending count drops below the threshold

See `references/budget.md` for the full interpretation guide.

## Risk Calibration Awareness

Before creating work items that involve risky actions, check for risk calibration
beliefs:

```bash
grep -rl "risk calibration" $CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/
```

Decision tree:
1. **Belief found, confidence >= 0.7**: User trusts the system — do not require
   permission for this action category
2. **Belief found, confidence < 0.3**: User wants to be asked — note in the work
   item that permission is required
3. **Belief found, 0.3-0.7**: Use judgment based on the specific action and stakes
4. **No belief found**: Default to requiring permission for risky actions

See `references/risk.md` for the full risk level table and promotion flow.
