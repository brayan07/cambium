# Planner — User Alignment Reference

## User-Assigned Tasks

When decomposing work that requires human action, set `assigned_to: "user"` on the child:

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/PARENT_ID/decompose" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "children": [
      {"title": "Research options", "priority": 2},
      {"title": "Run setup_oauth.py (requires your credentials)", "assigned_to": "user", "depends_on": ["$0"]},
      {"title": "Integrate OAuth", "depends_on": ["$1"]}
    ]
  }'
```

User tasks:
- Participate in normal dependency resolution
- Appear in the interlocutor's pending queue
- Should have clear, actionable descriptions

## Preference Requests

When you need a user preference to choose between approaches:

```bash
curl -s -X POST "$CAMBIUM_API_URL/requests" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "type": "preference",
    "summary": "Research depth for topic X",
    "detail": "Should I do a survey-level overview or deep technical analysis?",
    "options": ["survey", "deep-dive"],
    "default": "survey",
    "timeout_hours": 48
  }'
```

After creating a preference request:
- Proceed with the default
- The system may adjust later based on the user's answer
