# Detection

## Operational pattern detection (sentry)

Look for **operational patterns** visible from metrics that suggest a tunable change could help:

- A routine consistently times out → propose increasing its timeout config or simplifying its prompt
- A routine's episodes frequently end in `error` → propose a prompt change to improve reliability
- The reviewer rejects work at a high rate → propose clearer acceptance criteria in the planner prompt
- A specific channel has no events over multiple cycles → a routine may not be publishing correctly

Only propose when:
- The pattern is clear (not a one-off anomaly)
- The fix maps to a tunable file (prompt, routine config, timer config, skill)
- You have quantitative evidence (rates, counts, not just "seems like")

## Content-based pattern detection (consolidator)

During consolidation, look for patterns across session digests that suggest a tunable change:

- User corrections that recur → the relevant prompt may need updating
- Consistent quality issues in a routine's output → prompt or skill change
- Repeated failures with the same root cause → config or prompt adjustment

Only propose when:
- Grounded in evidence (not theoretical)
- Supported by at least 2 independent observations
- The fix is a change to a prompt, skill, or config parameter (not a code change)

For improvements that require code changes, use `improvement_proposal` type instead.

## Structured proposal format

Publish to `thoughts` channel:

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/thoughts/publish" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "payload": {
      "type": "self_improvement",
      "target_file": "adapters/claude-code/prompts/coordinator.md",
      "observation": "Coordinator creates vague work items without acceptance criteria in 60% of sessions",
      "proposed_change": "Add requirement for concrete deliverable and acceptance criteria in every work item",
      "evidence": ["sessions/2026-04-06/f8dc141b.md", "sessions/2026-04-07/abc123.md"]
    }
  }'
```

**Required fields:**
- `target_file`: Path relative to the config directory (must be tunable per `tunable-manifest.yaml`)
- `observation`: What pattern you observed (specific, quantified if possible)
- `proposed_change`: What to change and why it should help
- `evidence`: List of supporting references (session digests, episode data)

## Upstream update detection (sentry)

On each heartbeat, check for upstream framework changes:

```bash
REPO_DIR=$(git rev-parse --show-toplevel 2>/dev/null)
git -C "$REPO_DIR" remote get-url upstream 2>/dev/null
```

If the upstream remote exists, read `self_improvement.upstream_policy` from `defaults/config.yaml`. If the policy is `notify` or `auto`:

```bash
git -C "$REPO_DIR" fetch upstream 2>/dev/null
LAST_SYNCED=$(cat "$REPO_DIR/.cambium-version" 2>/dev/null)
```

If `.cambium-version` exists and there are new commits (`git log "$LAST_SYNCED..upstream/main" --oneline`):

1. First verify the user hasn't already merged upstream manually:
   ```bash
   git -C "$REPO_DIR" merge-base --is-ancestor upstream/main HEAD
   ```
   If this succeeds, update `.cambium-version` silently and skip.

2. Only report once per upstream HEAD — check recent `thoughts` events to avoid duplicates.

3. Publish to `thoughts`:
   ```bash
   curl -s -X POST "$CAMBIUM_API_URL/channels/thoughts/publish" \
     -H 'Content-Type: application/json' \
     -H "Authorization: Bearer $CAMBIUM_TOKEN" \
     -d '{
       "payload": {
         "type": "upstream_update",
         "upstream_commit": "'"$UPSTREAM_HEAD"'",
         "base_commit": "'"$LAST_SYNCED"'",
         "commit_count": '"$COMMIT_COUNT"',
         "policy": "<notify or auto>"
       }
     }'
   ```

## Upstream contribution detection (consolidator)

During weekly consolidation, if `self_improvement.contribute_upstream` is `true` in `defaults/config.yaml`, check for merged self-improvement PRs tagged for contribution:

```bash
gh pr list --state all --search "label:self-improvement label:contribute-upstream is:merged" --json number,title,mergeCommit --limit 10
```

For each, check if an upstream PR already exists:
```bash
gh pr list --repo <upstream-repo> --state all --search "user-improvement-<PR_NUMBER>" --json number
```

If not already contributed, publish to `thoughts`:

```bash
curl -s -X POST "$CAMBIUM_API_URL/channels/thoughts/publish" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "payload": {
      "type": "upstream_contribution",
      "source_pr": <number>,
      "merge_commit": "<sha>",
      "upstream_role": "<from config>"
    }
  }'
```
