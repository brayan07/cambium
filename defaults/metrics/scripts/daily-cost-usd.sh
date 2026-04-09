#!/bin/bash
# Deterministic metric: Total USD cost in past 24 hours.
# Reads session metadata.usage from the sessions API.
# Output: {"value": <float>, "detail": "<string>"}

SESSIONS=$(curl -s "${CAMBIUM_API_URL}/sessions?limit=200" 2>/dev/null)

python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta

sessions = json.loads(sys.stdin.read())
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

total_cost = 0.0
session_count = 0

for s in sessions:
    if s.get('created_at', '') < cutoff:
        continue
    usage = s.get('metadata', {}).get('usage', {})
    total_cost += usage.get('cost_usd', 0.0)
    if usage:
        session_count += 1

detail = f'\${total_cost:.4f} across {session_count} sessions'
print(json.dumps({'value': round(total_cost, 6), 'detail': detail}))
" <<< "$SESSIONS"
