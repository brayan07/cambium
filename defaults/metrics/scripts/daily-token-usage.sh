#!/bin/bash
# Deterministic metric: Total tokens consumed in past 24 hours.
# Reads session metadata.usage from the sessions API.
# Output: {"value": <float>, "detail": "<string>"}

SESSIONS=$(curl -s "${CAMBIUM_API_URL}/sessions?limit=200" 2>/dev/null)

python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta

sessions = json.loads(sys.stdin.read())
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

total_input = 0
total_output = 0
session_count = 0

for s in sessions:
    if s.get('created_at', '') < cutoff:
        continue
    usage = s.get('metadata', {}).get('usage', {})
    total_input += usage.get('input_tokens', 0)
    total_output += usage.get('output_tokens', 0)
    if usage:
        session_count += 1

total = total_input + total_output
detail = f'{total_input} input + {total_output} output across {session_count} sessions'
print(json.dumps({'value': total, 'detail': detail}))
" <<< "$SESSIONS"
