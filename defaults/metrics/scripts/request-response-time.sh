#!/bin/bash
# Deterministic metric: Average response time for answered requests (hours).
# Lower is better — measures how quickly the user responds to requests.
#
# Receives CAMBIUM_API_URL as environment variable.
# Must output JSON: {"value": <float>, "detail": "<string>"}

REQUESTS=$(curl -s "${CAMBIUM_API_URL}/requests?status=answered&limit=200" 2>/dev/null)

RESULT=$(echo "$REQUESTS" | python3 -c "
import json, sys
from datetime import datetime

try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        data = []

    deltas = []
    for r in data:
        created = r.get('created_at')
        answered = r.get('answered_at')
        if not created or not answered:
            continue
        t_created = datetime.fromisoformat(created)
        t_answered = datetime.fromisoformat(answered)
        hours = (t_answered - t_created).total_seconds() / 3600
        if hours >= 0:
            deltas.append(hours)

    if not deltas:
        print(json.dumps({'value': 0.0, 'detail': 'No answered requests with timestamps'}))
    else:
        avg = sum(deltas) / len(deltas)
        print(json.dumps({
            'value': round(avg, 2),
            'detail': f'Average {avg:.1f}h across {len(deltas)} answered requests'
        }))
except Exception as e:
    print(json.dumps({'value': 0.0, 'detail': f'Error: {str(e)}'}))
" 2>/dev/null)

echo "$RESULT"
