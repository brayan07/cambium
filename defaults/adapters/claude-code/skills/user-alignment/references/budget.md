# Attention Budget Reference

The attention budget is the system's awareness of how much user bandwidth is
available. It is a single belief file maintained by the memory consolidator.

## Reading the attention budget

```bash
cat $CAMBIUM_DATA_DIR/memory/knowledge/user/preferences/attention-budget.md 2>/dev/null
```

If the file does not exist, no calibration data is available yet. Use conservative
defaults: treat the user as moderately available (~5 requests/day tolerance).

The belief captures:
- **Typical response latency** — how long the user takes to answer requests
- **Daily request tolerance** — approximate number of requests the user handles per day
- **Expired-to-answered ratio** — high expiration means requests are too frequent or low-value

## Confidence interpretation

| Confidence | Interpretation |
|---|---|
| 0.7+ | Rely on the budget for queue management decisions |
| 0.4-0.6 | Soft guidance — don't suppress important requests based on this alone |
| < 0.4 | Insufficient data — fall back to conservative defaults |

## Overload detection (coordinator)

The coordinator checks the attention budget on each activation. Overload mode
activates when the number of pending requests exceeds the budget's daily tolerance.

In overload mode:
- **Do NOT** create work items that would generate new preference requests
- Add a note to work items: "User queue at capacity — planner should find approaches that do not require user input"
- Publish a thought noting the overload so the consolidator can track the pattern

Exit overload mode when pending requests drop below the tolerance threshold.

## What this is NOT

- Not a hard cap — no requests are programmatically blocked
- Not enforced by code — the coordinator LLM uses it as situational awareness
- Not a rate limiter — permission and information requests are never suppressed,
  only preference requests are deprioritized during overload
