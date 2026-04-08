#!/bin/bash
# Deterministic grader: Check that a reading was posted for a specific metric.
#
# Receives STAGING_API_URL as environment variable.
# Must output JSON: {"score": <float>, "details": "<string>"}

METRIC_NAME="goal_progress_estimate"

READINGS=$(curl -s "${STAGING_API_URL}/metrics/${METRIC_NAME}/readings?limit=5" 2>/dev/null)

COUNT=$(echo "$READINGS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        data = []
    print(len(data))
except:
    print(0)
" 2>/dev/null)

if [ "$COUNT" -gt 0 ] 2>/dev/null; then
    # Check that reading has a reasonable value (0-1 range for score_0_1)
    DETAIL=$(echo "$READINGS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    r = data[0]
    val = r.get('value', -1)
    detail = r.get('detail', '')
    source = r.get('source', '')
    if 0 <= val <= 1 and len(detail) > 0:
        print(json.dumps({'valid': True, 'value': val, 'detail': detail[:100], 'source': source}))
    else:
        print(json.dumps({'valid': False, 'value': val, 'detail': detail[:100]}))
except Exception as e:
    print(json.dumps({'valid': False, 'error': str(e)}))
" 2>/dev/null)

    VALID=$(echo "$DETAIL" | python3 -c "import json,sys; print(json.load(sys.stdin).get('valid', False))" 2>/dev/null)

    if [ "$VALID" = "True" ]; then
        echo "{\"score\": 1.0, \"details\": \"Reading posted for ${METRIC_NAME}: ${DETAIL}\"}"
    else
        echo "{\"score\": 0.5, \"details\": \"Reading posted but validation issue: ${DETAIL}\"}"
    fi
else
    echo "{\"score\": 0.0, \"details\": \"No readings found for ${METRIC_NAME}\"}"
fi
