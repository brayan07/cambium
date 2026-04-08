#!/bin/bash
# Deterministic grader: Check that preference belief files exist in memory.
#
# Receives STAGING_DATA_DIR and STAGING_API_URL as environment variables.
# Must output JSON: {"score": <float>, "details": "<string>"}

# Prompts use $CAMBIUM_DATA_DIR/memory/. In eval staging, the assertion runner
# passes STAGING_DATA_DIR which maps to the same directory.
MEMORY_DIR="${STAGING_DATA_DIR}/memory"
PREFS_DIR="${MEMORY_DIR}/knowledge/user/preferences"

# Check if memory directory exists
if [ ! -d "$MEMORY_DIR" ]; then
    echo '{"score": 0.0, "details": "No memory directory found"}'
    exit 0
fi

# Check if preferences directory exists
if [ ! -d "$PREFS_DIR" ]; then
    # Partial credit: check if any knowledge entries mention preferences
    KNOWLEDGE_DIR="${MEMORY_DIR}/knowledge"
    if [ -d "$KNOWLEDGE_DIR" ]; then
        PREF_MENTIONS=$(grep -rl "preference\|prefers\|prefer" "$KNOWLEDGE_DIR" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$PREF_MENTIONS" -gt 0 ]; then
            echo "{\"score\": 0.3, \"details\": \"No preferences/ directory but found $PREF_MENTIONS knowledge file(s) mentioning preferences\"}"
            exit 0
        fi
    fi
    echo '{"score": 0.0, "details": "No preferences directory in knowledge/user/"}'
    exit 0
fi

# Count preference belief files (excluding _archived/ and _index.md)
BELIEF_FILES=$(find "$PREFS_DIR" -maxdepth 1 -name "*.md" -not -name "_index.md" 2>/dev/null)
TOTAL_BELIEFS=$(echo "$BELIEF_FILES" | grep -c .)

if [ "$TOTAL_BELIEFS" -eq 0 ]; then
    echo '{"score": 0.1, "details": "Preferences directory exists but no belief files"}'
    exit 0
fi

# Check that belief files have proper frontmatter (title, confidence, last_confirmed)
VALID_BELIEFS=0
DETAILS=""

for file in $BELIEF_FILES; do
    HAS_TITLE=$(grep -c "^title:" "$file" 2>/dev/null)
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

echo "{\"score\": $SCORE, \"details\": \"$TOTAL_BELIEFS belief file(s), $VALID_BELIEFS with valid frontmatter. $DETAILS\"}"
