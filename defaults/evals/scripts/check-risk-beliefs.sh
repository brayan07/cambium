#!/bin/bash
# Deterministic grader: Check that risk calibration belief files exist in memory.
#
# Receives STAGING_DATA_DIR and STAGING_API_URL as environment variables.
# Must output JSON: {"score": <float>, "details": "<string>"}

MEMORY_DIR="${STAGING_DATA_DIR}/memory"
PREFS_DIR="${MEMORY_DIR}/knowledge/user/preferences"

# Check if memory directory exists
if [ ! -d "$MEMORY_DIR" ]; then
    echo '{"score": 0.0, "details": "No memory directory found"}'
    exit 0
fi

# Check if preferences directory exists
if [ ! -d "$PREFS_DIR" ]; then
    echo '{"score": 0.0, "details": "No preferences directory in knowledge/user/"}'
    exit 0
fi

# Find risk calibration belief files
RISK_FILES=$(find "$PREFS_DIR" -maxdepth 1 -name "risk-calibration-*.md" 2>/dev/null)
TOTAL_RISK=$(echo "$RISK_FILES" | grep -c .)

if [ "$TOTAL_RISK" -eq 0 ]; then
    # Check if any preference files mention risk calibration
    RISK_MENTIONS=$(grep -rl "risk calibration\|Risk calibration" "$PREFS_DIR" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$RISK_MENTIONS" -gt 0 ]; then
        echo "{\"score\": 0.3, \"details\": \"No risk-calibration-*.md files but found $RISK_MENTIONS file(s) mentioning risk calibration\"}"
        exit 0
    fi
    echo '{"score": 0.0, "details": "No risk calibration belief files found"}'
    exit 0
fi

# Validate frontmatter of risk calibration files
VALID_BELIEFS=0
DETAILS=""

for file in $RISK_FILES; do
    HAS_TITLE=$(grep -ci "^title:.*risk calibration" "$file" 2>/dev/null)
    HAS_CONFIDENCE=$(grep -c "^confidence:" "$file" 2>/dev/null)
    HAS_CONFIRMED=$(grep -c "^last_confirmed:" "$file" 2>/dev/null)

    BASENAME=$(basename "$file")
    if [ "$HAS_TITLE" -gt 0 ] && [ "$HAS_CONFIDENCE" -gt 0 ] && [ "$HAS_CONFIRMED" -gt 0 ]; then
        VALID_BELIEFS=$((VALID_BELIEFS + 1))
        DETAILS="${DETAILS}${BASENAME} (valid); "
    else
        DETAILS="${DETAILS}${BASENAME} (missing frontmatter); "
    fi
done

if [ "$VALID_BELIEFS" -gt 0 ]; then
    SCORE="1.0"
else
    SCORE="0.3"
fi

echo "{\"score\": $SCORE, \"details\": \"$TOTAL_RISK risk belief file(s), $VALID_BELIEFS with valid frontmatter. $DETAILS\"}"
