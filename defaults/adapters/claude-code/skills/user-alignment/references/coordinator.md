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
