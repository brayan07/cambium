#!/bin/bash
# Deterministic grader: Check that a PREFERENCE request was created for a
# preference conflict (challenge protocol).
#
# Receives STAGING_DATA_DIR and STAGING_API_URL as environment variables.
# Must output JSON: {"score": <float>, "details": "<string>"}

# Query all requests from the staging API
REQUESTS=$(curl -s "${STAGING_API_URL}/requests" 2>/dev/null)

if [ -z "$REQUESTS" ] || [ "$REQUESTS" = "[]" ] || [ "$REQUESTS" = "null" ]; then
    echo '{"score": 0.0, "details": "No requests found in the system"}'
    exit 0
fi

# Check if any request mentions a preference conflict or challenge
CONFLICT_REQUESTS=$(echo "$REQUESTS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        data = [data]
    matches = []
    for r in data:
        rtype = str(r.get('type', '')).lower()
        summary = str(r.get('summary', '')).lower()
        detail = str(r.get('detail', '') or '').lower()
        # Look for preference-type requests about conflicts/contradictions
        if rtype == 'preference' and any(kw in summary + detail for kw in ['conflict', 'contradict', 'challenge', 'changed', 'different', 'previous preference']):
            matches.append(r.get('summary', 'unknown'))
    print(json.dumps({'count': len(matches), 'summaries': matches}))
except Exception as e:
    print(json.dumps({'count': 0, 'summaries': [], 'error': str(e)}))
" 2>/dev/null)

COUNT=$(echo "$CONFLICT_REQUESTS" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)
SUMMARIES=$(echo "$CONFLICT_REQUESTS" | python3 -c "import json,sys; print('; '.join(json.load(sys.stdin).get('summaries',[])))" 2>/dev/null)

if [ "$COUNT" -gt 0 ] 2>/dev/null; then
    echo "{\"score\": 1.0, \"details\": \"Found $COUNT challenge request(s): $SUMMARIES\"}"
else
    # Partial credit if any preference request exists at all
    ANY_PREF=$(echo "$REQUESTS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
if not isinstance(data, list):
    data = [data]
prefs = [r for r in data if str(r.get('type','')).lower() == 'preference']
print(len(prefs))
" 2>/dev/null)
    if [ "$ANY_PREF" -gt 0 ] 2>/dev/null; then
        echo "{\"score\": 0.3, \"details\": \"Found $ANY_PREF preference request(s) but none clearly about a conflict\"}"
    else
        echo '{"score": 0.0, "details": "No preference requests created"}'
    fi
fi
