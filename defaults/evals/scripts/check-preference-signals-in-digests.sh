#!/bin/bash
# Deterministic grader: Check that session digests contain Preference Signals sections.
#
# Receives STAGING_DATA_DIR and STAGING_API_URL as environment variables.
# Must output JSON: {"score": <float>, "details": "<string>"}

# Prompts use $CAMBIUM_DATA_DIR/memory/. In eval staging, the assertion runner
# passes STAGING_DATA_DIR which maps to the same directory.
MEMORY_DIR="${STAGING_DATA_DIR}/memory"
SESSIONS_DIR="${MEMORY_DIR}/sessions"

# Check if memory directory exists
if [ ! -d "$MEMORY_DIR" ]; then
    echo '{"score": 0.0, "details": "No memory directory found"}'
    exit 0
fi

# Check if sessions directory exists
if [ ! -d "$SESSIONS_DIR" ]; then
    echo '{"score": 0.0, "details": "No sessions directory found in memory"}'
    exit 0
fi

# Find all digest files (excluding _index.md)
DIGEST_FILES=$(find "$SESSIONS_DIR" -name "*.md" -not -name "_index.md" 2>/dev/null)
TOTAL_DIGESTS=$(echo "$DIGEST_FILES" | grep -c .)

if [ "$TOTAL_DIGESTS" -eq 0 ]; then
    echo '{"score": 0.0, "details": "No digest files found"}'
    exit 0
fi

# Count digests that have a "Preference Signals" section
DIGESTS_WITH_SIGNALS=0
SIGNAL_DETAILS=""

for file in $DIGEST_FILES; do
    if grep -q "## Preference Signals" "$file" 2>/dev/null; then
        # Check it's not just "None detected"
        SIGNALS_CONTENT=$(sed -n '/## Preference Signals/,/^##/p' "$file" | grep -v "^##" | grep -v "None detected" | grep -c ".")
        if [ "$SIGNALS_CONTENT" -gt 0 ]; then
            DIGESTS_WITH_SIGNALS=$((DIGESTS_WITH_SIGNALS + 1))
            BASENAME=$(basename "$file")
            SIGNAL_DETAILS="${SIGNAL_DETAILS}${BASENAME} has signals; "
        fi
    fi
done

# Score: at least one digest should have preference signals with content
if [ "$DIGESTS_WITH_SIGNALS" -gt 0 ]; then
    SCORE="1.0"
else
    # Partial credit if the section header exists (even with "None detected")
    HEADER_COUNT=$(grep -rl "## Preference Signals" "$SESSIONS_DIR" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$HEADER_COUNT" -gt 0 ]; then
        SCORE="0.3"
        SIGNAL_DETAILS="Found $HEADER_COUNT digest(s) with Preference Signals header but no actual signals"
    else
        SCORE="0.0"
        SIGNAL_DETAILS="No digests contain a Preference Signals section"
    fi
fi

echo "{\"score\": $SCORE, \"details\": \"$TOTAL_DIGESTS digest(s), $DIGESTS_WITH_SIGNALS with preference signals. $SIGNAL_DETAILS\"}"
