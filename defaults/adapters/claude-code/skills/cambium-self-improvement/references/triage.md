# Triage

When processing messages on the `thoughts` channel, handle these self-improvement-related payload types.

## `type: "self_improvement"` — tunable change proposal

Preserve the structured fields when creating the work item:

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "title": "Self-improvement: <concise description of the proposed change>",
    "description": "Self-improvement proposal from <source routine>.\n\nTarget: <target_file>\nObservation: <observation>\nProposed change: <proposed_change>",
    "priority": 3,
    "context": {
      "type": "self_improvement",
      "target_file": "<from payload>",
      "observation": "<from payload>",
      "proposed_change": "<from payload>",
      "evidence": ["<from payload>"]
    }
  }'
```

Use priority 3 (low-medium) — self-improvement should not preempt user-requested work unless the observation indicates a critical quality issue.

## `type: "upstream_update"` — new upstream commits

Check for duplicates first — if an active upstream merge work item already exists, skip.

If policy is `notify`:
```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "title": "Upstream has <commit_count> new commits (notification only)",
    "description": "The upstream Cambium framework has new changes. Run cambium update manually to merge.\n\nUpstream commit: <upstream_commit>\nBase commit: <base_commit>",
    "priority": 2,
    "context": {
      "type": "upstream_notification",
      "upstream_commit": "<from payload>",
      "base_commit": "<from payload>"
    }
  }'
```

If policy is `auto`:
```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "title": "Merge upstream changes (<commit_count> commits)",
    "description": "Upstream has <commit_count> new commits since last sync.\n\nUpstream commit: <upstream_commit>\nBase commit: <base_commit>",
    "priority": 5,
    "context": {
      "type": "upstream_merge",
      "upstream_commit": "<from payload>",
      "base_commit": "<from payload>"
    }
  }'
```

The planner classifies files during decomposition — the coordinator does not need to.

## `type: "upstream_contribution"` — PR tagged for upstream

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "title": "Contribute improvement upstream: <title>",
    "description": "Merged self-improvement PR #<source_pr> has the contribute-upstream label.",
    "priority": 2,
    "context": {
      "type": "upstream_contribution",
      "source_pr": "<from payload>",
      "merge_commit": "<from payload>",
      "upstream_role": "<from payload>"
    }
  }'
```
