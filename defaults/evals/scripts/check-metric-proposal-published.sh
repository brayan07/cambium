#!/bin/bash
# Deterministic grader: Verify the consolidator published a metric-driven
# self-improvement proposal to the thoughts channel.
#
# Checks that at least one event on 'thoughts' references the declining
# metric (goal_progress) and is a self_improvement proposal.
#
# Receives STAGING_API_URL as environment variable.
# Must output JSON: {"score": <float>, "details": "<string>"}

EVENTS=$(curl -s "${STAGING_API_URL}/events?channel=thoughts&limit=50" 2>/dev/null)

echo "$EVENTS" | python3 -c "
import json, sys

try:
    events = json.load(sys.stdin)
except Exception:
    events = []

if not isinstance(events, list):
    events = []

if len(events) == 0:
    print(json.dumps({'score': 0.0, 'details': 'No events on thoughts channel'}))
    sys.exit(0)

# Look for an event whose payload references goal_progress AND is a
# self_improvement or improvement_proposal type
found = []
for ev in events:
    payload = ev.get('payload', {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            continue

    payload_str = json.dumps(payload).lower()
    ev_type = payload.get('type', '')

    has_metric_ref = 'goal_progress' in payload_str
    is_improvement = ev_type in ('self_improvement', 'improvement_proposal', 'health_observation')

    if has_metric_ref and is_improvement:
        found.append({
            'type': ev_type,
            'observation': payload.get('observation', payload.get('detail', ''))[:120],
        })

if found:
    detail = f'Found {len(found)} metric-driven proposal(s): {found[0][\"type\"]} — {found[0][\"observation\"]}'
    print(json.dumps({'score': 1.0, 'details': detail}))
elif any('goal_progress' in json.dumps(ev.get('payload', {})).lower() for ev in events):
    print(json.dumps({'score': 0.5, 'details': 'Found goal_progress reference but not as self_improvement type'}))
else:
    types = [ev.get('payload', {}).get('type', 'unknown') for ev in events]
    print(json.dumps({'score': 0.0, 'details': f'No metric-driven proposals found. Event types: {types}'}))
"
