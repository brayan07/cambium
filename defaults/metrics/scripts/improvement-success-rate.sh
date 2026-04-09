#!/bin/bash
# Deterministic metric: Self-improvement work item acceptance rate.
# Returns ratio of accepted / (accepted + rejected) self-improvement items
# completed in the past 30 days.
#
# Receives CAMBIUM_API_URL as environment variable.
# Must output JSON: {"value": <float>, "detail": "<string>"}

# Fetch completed and failed work items (both represent reviewed outcomes)
COMPLETED=$(curl -s "${CAMBIUM_API_URL}/work-items?status=completed&limit=200" 2>/dev/null)
FAILED=$(curl -s "${CAMBIUM_API_URL}/work-items?status=failed&limit=200" 2>/dev/null)

# Use Python to filter self-improvement items and compute ratio
python3 -c "
import json, sys
from datetime import datetime, timedelta, timezone

cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

def parse_items(raw):
    try:
        data = json.loads(raw)
        items = data.get('items', []) if isinstance(data, dict) else data
        return [i for i in items if isinstance(i, dict)]
    except Exception:
        return []

completed = parse_items('''$COMPLETED''')
failed = parse_items('''$FAILED''')

# Filter to self-improvement items updated in the past 30 days
accepted = 0
rejected = 0

for item in completed:
    ctx = item.get('context', {})
    if ctx.get('type') != 'self_improvement':
        continue
    if item.get('updated_at', '') < cutoff:
        continue
    # Completed items that were reviewed are accepted
    if item.get('reviewed_by'):
        accepted += 1

for item in failed:
    ctx = item.get('context', {})
    if ctx.get('type') != 'self_improvement':
        continue
    if item.get('updated_at', '') < cutoff:
        continue
    rejected += 1

total = accepted + rejected

if total == 0:
    print(json.dumps({'value': 1.0, 'detail': 'No self-improvement items reviewed in past 30 days'}))
else:
    rate = round(accepted / total, 4)
    print(json.dumps({'value': rate, 'detail': f'{accepted} accepted, {rejected} rejected ({total} total)'}))
"
