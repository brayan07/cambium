#!/bin/bash
# Deterministic grader: Check that the coordinator handled overload correctly.
#
# When the user queue is overloaded, the coordinator should:
# 1. Create a work item (it still processes the goal)
# 2. The work item description should mention overload/capacity
# 3. No NEW preference requests should be created by the coordinator
#
# Receives STAGING_DATA_DIR and STAGING_API_URL as environment variables.
# Must output JSON: {"score": <float>, "details": "<string>"}

# Check that a work item was created
WORK_ITEMS=$(curl -s "${STAGING_API_URL}/work-items" 2>/dev/null)
WI_COUNT=$(echo "$WORK_ITEMS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if isinstance(data, dict) and 'items' in data:
        data = data['items']
    if not isinstance(data, list):
        data = []
    print(len(data))
except:
    print(0)
" 2>/dev/null)

if [ "$WI_COUNT" -eq 0 ] 2>/dev/null; then
    echo '{"score": 0.0, "details": "No work items created — coordinator may not have processed the goal"}'
    exit 0
fi

# Check if any work item mentions overload/capacity
OVERLOAD_MENTIONS=$(echo "$WORK_ITEMS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if isinstance(data, dict) and 'items' in data:
        data = data['items']
    if not isinstance(data, list):
        data = []
    keywords = ['overload', 'capacity', 'queue', 'at capacity', 'user input', 'autonomous']
    matches = []
    for wi in data:
        desc = str(wi.get('description', '') or '').lower()
        title = str(wi.get('title', '') or '').lower()
        text = desc + ' ' + title
        if any(kw in text for kw in keywords):
            matches.append(wi.get('title', 'unknown'))
    print(json.dumps({'count': len(matches), 'titles': matches}))
except Exception as e:
    print(json.dumps({'count': 0, 'titles': [], 'error': str(e)}))
" 2>/dev/null)

OVERLOAD_COUNT=$(echo "$OVERLOAD_MENTIONS" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)

# Check that no NEW preference requests were created (beyond the seeded ones)
REQUESTS=$(curl -s "${STAGING_API_URL}/requests" 2>/dev/null)
NEW_PREF_REQUESTS=$(echo "$REQUESTS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        data = [data]
    # Count preference requests NOT created by 'seed' (i.e., created by coordinator)
    new_prefs = [r for r in data if str(r.get('type','')).lower() == 'preference' and r.get('created_by') != 'seed']
    print(len(new_prefs))
except:
    print(0)
" 2>/dev/null)

# Scoring
if [ "$OVERLOAD_COUNT" -gt 0 ] 2>/dev/null && [ "$NEW_PREF_REQUESTS" -eq 0 ] 2>/dev/null; then
    echo "{\"score\": 1.0, \"details\": \"Work item mentions overload ($OVERLOAD_COUNT), no new preference requests created. $WI_COUNT work item(s) total.\"}"
elif [ "$OVERLOAD_COUNT" -gt 0 ] 2>/dev/null; then
    echo "{\"score\": 0.5, \"details\": \"Work item mentions overload but $NEW_PREF_REQUESTS new preference request(s) were created despite overload.\"}"
elif [ "$NEW_PREF_REQUESTS" -eq 0 ] 2>/dev/null; then
    echo "{\"score\": 0.3, \"details\": \"No new preference requests (good) but work items don't mention overload. $WI_COUNT work item(s) created.\"}"
else
    echo "{\"score\": 0.0, \"details\": \"$NEW_PREF_REQUESTS new preference request(s) created despite overload, no overload mention in work items.\"}"
fi
