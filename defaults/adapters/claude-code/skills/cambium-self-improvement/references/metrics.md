# Metric System Reference

Cambium's metric system provides quantitative observability — a "loss function" for self-improvement.

## Three Metric Types

| Type | Produced by | How |
|------|------------|-----|
| **Deterministic** | MetricRunner (Python) | Bash script executed on cron schedule |
| **Survey** | User | SURVEY request fired on schedule, response recorded as reading |
| **Intelligent** | Metric-analyst routine (LLM) | Dispatched by MetricRunner when due, posts reading via API |

## Reading a Metric via API

```bash
# List all metrics
GET $CAMBIUM_API_URL/metrics

# Get a specific metric definition
GET $CAMBIUM_API_URL/metrics/{name}

# Get recent readings
GET $CAMBIUM_API_URL/metrics/{name}/readings?limit=10&since={iso_date}

# Get aggregated summary (min, max, avg, count, latest)
GET $CAMBIUM_API_URL/metrics/{name}/summary?since={iso_date}
```

## Posting an Intelligent Reading

Only the metric-analyst routine should post readings for intelligent metrics. Other routines should read metrics for decision-making, not produce them.

```bash
POST $CAMBIUM_API_URL/metrics/{name}/readings
{
  "value": 0.6,
  "detail": "3 of 5 weekly objectives completed",
  "source": "metric-analyst"
}
```

## Using Metrics for Self-Improvement

When reviewing metric trends:
- **Declining trend** (3+ drops): Investigate root cause, propose corrective action
- **Stable low value**: May indicate a systemic issue worth a self-improvement proposal
- **Improving trend**: Evidence that a recent change is working — note in relevant beliefs
- **Missing readings**: Check if the metric runner is healthy

## Metric-Driven Self-Improvement Proposals

When proposing a self-improvement change based on metric evidence, include metric data in the `evidence` array with a `metric:` prefix so downstream routines can distinguish metric data from session references:

```json
{
  "type": "self_improvement",
  "target_file": "adapters/claude-code/prompts/executor.md",
  "observation": "weekly_alignment_rating declined from 4.2 to 2.8 over 3 weeks",
  "proposed_change": "Add preference-checking step before executing subjective tasks",
  "evidence": [
    "metric:weekly_alignment_rating readings 4.2→3.5→2.8 (weeks 13-15)",
    "knowledge/metrics/trend-weekly_alignment_rating.md",
    "sessions/2026-04-08/abc.md"
  ]
}
```

**When metric evidence strengthens a proposal:**
- 3+ readings showing a clear trend (not noise)
- Temporal correlation with a specific change (belief update, PR merge, config tweak)
- Corroboration from multiple metrics (e.g., both alignment rating AND goal progress declining)

**When metric evidence is insufficient:**
- Fewer than 3 readings — observation only, not actionable
- Volatile readings with no clear direction
- Single metric moving without corroborating signals

**Target files for metric-driven proposals** (most to least common):
- Routine prompts: `adapters/claude-code/prompts/*.md`
- Skills: `adapters/claude-code/skills/*/SKILL.md`
- Timer config: `timers.yaml` (when metric collection frequency is the issue)
- Routine config: `routines/*.yaml` (when concurrency or channel routing is the issue)

## Metric Definitions

Metrics are defined in `defaults/metrics.yaml` — YAML config, not database entries. Routines cannot create new metrics via API. To propose a new metric, file a self-improvement proposal suggesting additions to the YAML config.
