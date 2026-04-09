#!/bin/bash
# Deterministic metric: Request answer rate over past 7 days.
# Returns ratio of answered / (answered + expired). Higher is better.
#
# Receives CAMBIUM_API_URL as environment variable.
# Must output JSON: {"value": <float>, "detail": "<string>"}

SUMMARY=$(curl -s "${CAMBIUM_API_URL}/requests/summary" 2>/dev/null)

ANSWERED=$(echo "$SUMMARY" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    counts = data.get('counts', {})
    total = 0
    for type_counts in counts.values():
        total += type_counts.get('answered', 0)
    print(total)
except:
    print(0)
" 2>/dev/null)

EXPIRED=$(echo "$SUMMARY" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    counts = data.get('counts', {})
    total = 0
    for type_counts in counts.values():
        total += type_counts.get('expired', 0)
    print(total)
except:
    print(0)
" 2>/dev/null)

TOTAL=$((ANSWERED + EXPIRED))

if [ "$TOTAL" -eq 0 ] 2>/dev/null; then
    echo '{"value": 1.0, "detail": "No answered or expired requests in window"}'
else
    RATE=$(python3 -c "print(round($ANSWERED / $TOTAL, 4))")
    echo "{\"value\": $RATE, \"detail\": \"$ANSWERED answered, $EXPIRED expired ($TOTAL total)\"}"
fi
