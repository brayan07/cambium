# Risk Calibration Reference

Risk calibration beliefs track the user's trust level for categories of autonomous
action. They are a specific category of preference beliefs, filed as
`risk-calibration-{category-slug}.md` in `$CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/`.

## Reading risk beliefs

Before taking an action that could require user permission, check for a relevant
risk calibration belief:

```bash
grep -rl "risk calibration" $CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/
```

Read any matching files. The confidence level indicates how much autonomy the user
has granted for that action category:

| Confidence | Risk level | What to do |
|---|---|---|
| < 0.3 | Always ask | Create a permission request every time |
| 0.3-0.5 | Usually ask | Ask unless the action is trivial or time-sensitive |
| 0.5-0.7 | Usually proceed | Proceed with notification; ask only for unusual cases |
| 0.7+ | Always proceed | Full autonomy for this action category |

## Example belief file

```markdown
---
title: Risk calibration — wiki publishing
confidence: 0.8
last_confirmed: 2026-04-07
---
User trusts the system to publish wiki entries without permission.

**Evidence:**
- 2026-03-15: approved wiki publish without discussion
- 2026-03-22: approved wiki publish, said "looks good"
- 2026-03-29: approved wiki publish immediately
- 2026-04-05: approved wiki publish without discussion
- 2026-04-07: system proposed autonomy, user confirmed "Yes, proceed autonomously"
```

## Who writes risk beliefs

Only the **memory consolidator** creates and updates risk calibration beliefs,
during weekly consolidation. Other routines read them.

## The promotion flow

This is the critical safety invariant. The system **never** silently increases
its own autonomy.

1. The consolidator detects a pattern: 5+ consecutive approvals for the same
   action category over 2+ weeks, with no rejections
2. The consolidator creates a PREFERENCE request:
   - Summary: "Risk calibration: auto-approve [category]?"
   - Detail: explains the pattern (N approvals, 0 rejections, over M weeks)
   - Options: `["Yes, proceed autonomously", "No, keep asking"]`
   - **Default: "No, keep asking"**
   - Timeout: 168 hours (1 week)
3. Only if the user **explicitly answers "Yes"** does the consolidator increase
   the belief's confidence
4. If the user answers "No" or the request **expires**: no change. The system
   continues asking for permission.

Silence is NOT consent. Expiration does NOT increase autonomy.

## Demotion

Demotion is immediate and requires no preference request:
- If the user **rejects** a previously-autonomous action, the consolidator
  immediately lowers the belief's confidence and adds contradicting evidence
- A single rejection can drop confidence significantly (e.g., from 0.8 to 0.4)
- The system resumes asking for permission at the new risk level

## What is NOT risk calibration

- One-time situational decisions ("skip review this time because it's urgent")
- Constitutional values (those are non-negotiable, not calibratable)
- General preference beliefs (those track how, not whether)
