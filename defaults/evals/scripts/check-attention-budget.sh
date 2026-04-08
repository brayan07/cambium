#!/bin/bash
# Deterministic grader: Check that an attention budget belief file exists in memory.
#
# Receives STAGING_DATA_DIR and STAGING_API_URL as environment variables.
# Must output JSON: {"score": <float>, "details": "<string>"}

MEMORY_DIR="${STAGING_DATA_DIR}/memory"
PREFS_DIR="${MEMORY_DIR}/knowledge/user/preferences"
BUDGET_FILE="${PREFS_DIR}/attention-budget.md"

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

# Check if attention budget file exists
if [ ! -f "$BUDGET_FILE" ]; then
    # Check if any file mentions attention budget
    BUDGET_MENTIONS=$(grep -rl "attention.budget\|Attention.budget" "$PREFS_DIR" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$BUDGET_MENTIONS" -gt 0 ]; then
        echo "{\"score\": 0.3, \"details\": \"No attention-budget.md but found $BUDGET_MENTIONS file(s) mentioning attention budget\"}"
        exit 0
    fi
    echo '{"score": 0.0, "details": "No attention-budget.md file found"}'
    exit 0
fi

# Validate frontmatter
HAS_TITLE=$(grep -c "^title:" "$BUDGET_FILE" 2>/dev/null)
HAS_CONFIDENCE=$(grep -c "^confidence:" "$BUDGET_FILE" 2>/dev/null)
HAS_CONFIRMED=$(grep -c "^last_confirmed:" "$BUDGET_FILE" 2>/dev/null)

if [ "$HAS_TITLE" -eq 0 ] || [ "$HAS_CONFIDENCE" -eq 0 ] || [ "$HAS_CONFIRMED" -eq 0 ]; then
    echo '{"score": 0.3, "details": "attention-budget.md exists but missing required frontmatter (title, confidence, last_confirmed)"}'
    exit 0
fi

# Check body has meaningful content (response latency or capacity info)
BODY_LINES=$(sed -n '/^---$/,/^---$/d;p' "$BUDGET_FILE" | grep -c ".")
if [ "$BODY_LINES" -lt 2 ]; then
    echo '{"score": 0.5, "details": "attention-budget.md has valid frontmatter but minimal body content"}'
    exit 0
fi

echo '{"score": 1.0, "details": "attention-budget.md exists with valid frontmatter and body content"}'
