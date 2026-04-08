# Preference Beliefs Reference

Preference beliefs are the system's learned understanding of how the user wants
things done. They live in `$CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/`.

## Reading preferences

Before making a judgment call that has multiple reasonable approaches, check for
relevant preference beliefs:

```bash
ls $CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/
grep -rl "keyword" $CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/
```

Read any matching files. Use the confidence level to calibrate how strongly to
follow the preference:

| Confidence | Interpretation |
|---|---|
| 0.9-1.0 | Treat as a standing instruction — follow unless the user says otherwise |
| 0.7-0.8 | Strong default — follow, but mention you're doing so if the choice is visible |
| 0.5-0.6 | Lean toward this, but consider asking if the stakes are high |
| < 0.5 | Weak signal — don't rely on it, consider asking |

## Who writes preferences

Only the **memory consolidator** creates and updates preference files. Other routines
read them. The session-summarizer embeds preference signals in session digests,
which the consolidator processes into beliefs.

## Lifecycle

1. Session-summarizer detects a preference signal → embeds it in the digest + publishes `preference_signal` thought
2. Consolidator reads digest → creates/updates/challenges preference belief
3. Routines read beliefs before judgment calls
4. Stale beliefs decay (confidence lowered weekly if unconfirmed for 60+ days)
5. Contradicted high-confidence beliefs → preference request to user

## What is NOT a preference

- One-time situational decisions ("skip tests this time")
- Constitutional values (those live in the constitution, not here)
- Risk calibration (see `references/risk.md` — separate belief category)
- Technical facts (those are regular knowledge entries)
