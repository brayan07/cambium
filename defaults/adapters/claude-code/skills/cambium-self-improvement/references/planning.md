# Planning

## Gate checks

When a work item has `context.type == "self_improvement"`, run these gates before decomposing:

**Gate 1 — GitHub remote:**
```bash
git remote get-url origin
```
If this fails: "Self-improvement requires a GitHub remote. Run `cambium init --github`." Stop.

**Gate 2 — PR budget:**
```bash
gh pr list --label self-improvement --state open --json number
```
Compare against `defaults/config.yaml` → `self_improvement.max_pending_improvement_prs`. If at or above cap: "Self-improvement PR budget exhausted (N/M open)." Stop.

**Gate 3 — Tunable manifest:**
Read `defaults/tunable-manifest.yaml`. Verify `target_file` matches a `tunable` entry and is not `protected`. If not: "Target file is not tunable: {path}." Stop.

## Self-improvement decomposition

If all gates pass, decompose into exactly **2 tasks**:

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/{work_item_id}/decompose" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "children": [
      {
        "title": "Write eval + baseline for: {observation_summary}",
        "description": "SELF-IMPROVEMENT TASK 1\n\nTarget: {target_file}\nObservation: {observation}\nProposed change: {proposed_change}\nEvidence: {evidence_list}\n\nWrite an eval config that tests the target behavior, run it as baseline on current code, and commit the eval + baseline to the repo. Store file paths in work item context.",
        "priority": 1
      },
      {
        "title": "Test change + PR for: {observation_summary}",
        "description": "SELF-IMPROVEMENT TASK 2\n\nRead eval path, override path, and baseline path from work item context (set by Task 1). Run comparison eval with the proposed override. If improved or maintained, create a PR with the change. If regressed, report failure.",
        "depends_on": ["$0"]
      }
    ]
  }'
```

The `SELF-IMPROVEMENT TASK 1` / `SELF-IMPROVEMENT TASK 2` prefixes are how the executor identifies self-improvement work.

## Upstream merge decomposition

When `context.type == "upstream_merge"`, decompose into **2 tasks**:

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/{work_item_id}/decompose" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "children": [
      {
        "title": "Merge upstream changes to branch",
        "description": "UPSTREAM MERGE — IMPLEMENT\n\nUpstream commit: {upstream_commit}\nBase commit: {base_commit}\n\nClassify changed files (trivial vs. conflicting), create merge branch, apply all changes, and push. Store branch name and merge decisions in work item context.",
        "priority": 5
      },
      {
        "title": "Eval + PR for upstream merge",
        "description": "UPSTREAM MERGE — EVAL + PR\n\nUpstream commit: {upstream_commit}\n\nRead the merge branch name from work item context (set by Task 1). Run canary eval on the branch. If passing, update .cambium-version and create PR with changelog and merge decisions. If failing, report failures.",
        "depends_on": ["$0"]
      }
    ]
  }'
```

## Upstream contribution decomposition

When `context.type == "upstream_contribution"`, decompose into **1 task**:

```bash
curl -s -X POST "$CAMBIUM_API_URL/work-items/{work_item_id}/decompose" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "children": [
      {
        "title": "Create upstream PR for improvement: {source_pr_title}",
        "description": "UPSTREAM CONTRIBUTION\n\nSource PR: #{source_pr}\nMerge commit: {merge_commit}\nUpstream role: {upstream_role}\n\nCherry-pick the merge commit to the upstream repo and create a PR.",
        "priority": 2
      }
    ]
  }'
```
