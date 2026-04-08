#!/bin/bash
# Deterministic grader: Check that a reading was posted for a specific metric.
#
# Receives STAGING_API_URL as environment variable.
# Must output JSON: {"score": <float>, "details": "<string>"}

METRIC_NAME="goal_progress_estimate"

READINGS=$(curl -s "${STAGING_API_URL}/metrics/${METRIC_NAME}/readings?limit=5" 2>/dev/null)

# Use Python to parse and produce valid JSON output (avoids shell quoting issues)
echo "$READINGS" | python3 -c "
import json, sys

try:
    data = json.load(sys.stdin)
except Exception:
    data = []

if not isinstance(data, list):
    data = []

if len(data) == 0:
    print(json.dumps({'score': 0.0, 'details': 'No readings found for ${METRIC_NAME}'}))
    sys.exit(0)

r = data[0]
val = r.get('value', -1)
detail = r.get('detail', '')
source = r.get('source', '')

if 0 <= val <= 1 and len(detail) > 0:
    msg = f'Reading posted for ${METRIC_NAME}: value={val}, source={source}, detail={detail[:100]}'
    print(json.dumps({'score': 1.0, 'details': msg}))
else:
    msg = f'Reading posted but validation issue: value={val}, detail={detail[:100]}'
    print(json.dumps({'score': 0.5, 'details': msg}))
"
