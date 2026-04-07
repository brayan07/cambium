---
name: cambium-contribute
description: Contribute merged self-improvements back to the upstream Cambium framework
---

# Cambium Contribute

This skill handles pushing merged self-improvement PRs back to the upstream Cambium framework. It is used by the executor when processing upstream contribution work items. The memory consolidator detects labeled PRs and routes them through the coordinator and planner.

## Prerequisites

- The repo must have an `upstream` remote: `git remote get-url upstream`
- `self_improvement.contribute_upstream` must be `true` in `defaults/config.yaml`
- `gh` CLI must be authenticated with appropriate access

## Data Safety — CRITICAL

Contributions push code to a **public upstream repository**. You MUST audit the diff before pushing:

1. **No credentials or secrets**: Search the diff for API keys, tokens, passwords, `.env` values, OAuth secrets, private URLs. If ANY are present, **stop immediately** — fail the task.
2. **No private user data**: Strip references to the user's name, email, organization, file paths, server URLs, or any personally identifiable information from both the code and the PR body.
3. **No user-specific customizations**: The cherry-picked change may include user customizations alongside the improvement. During conflict resolution, keep ONLY the generalizable improvement — remove anything specific to the user's workflow, preferences, or environment.
4. **Audit the full diff**: Before pushing, run `git diff main..HEAD` and review every line. If in doubt about whether something is private, fail the task and explain what you found.

**The PR body must not reference**: the user's repo URL, their GitHub username (unless they are the upstream author), specific session digests, or any internal system details beyond what the improvement itself describes.

## Task Type

### UPSTREAM CONTRIBUTION

Cherry-pick a merged self-improvement from the user's repo to the upstream framework and create a PR.

**Inputs** (from work item description/context): source PR number, merge commit SHA, upstream role (`author` or `contributor`).

#### Step 0 — Verify feature flag

```bash
REPO_DIR=$(git rev-parse --show-toplevel)
cd "$REPO_DIR"
```

Read `defaults/config.yaml` and check that `self_improvement.contribute_upstream` is `true`. If it is `false` or missing, **stop** — fail the task with: "Upstream contributions are disabled. Set `contribute_upstream: true` in config.yaml to enable."

#### Step 1 — Read config and validate

```bash
UPSTREAM_URL=$(git remote get-url upstream)
```

Extract the upstream owner/repo from the URL (e.g., `brayan07/cambium` from `https://github.com/brayan07/cambium.git`).

Read `upstream_role` from `defaults/config.yaml` → `self_improvement.upstream_role`.

#### Step 2 — Gather source PR details

```bash
# Get the original PR body and title for the contribution PR
gh pr view "$SOURCE_PR" --json title,body,labels
```

#### Step 3a — Author mode (direct push access)

If `upstream_role` is `author`:

```bash
# Clone upstream to a temp dir
TEMP=$(mktemp -d)
git clone "$UPSTREAM_URL" "$TEMP/upstream"
cd "$TEMP/upstream"
git checkout -b "contribute/user-improvement-$SOURCE_PR"

# Cherry-pick from the user's repo
git remote add user-repo "$REPO_DIR"
git fetch user-repo
git cherry-pick "$MERGE_COMMIT"

# DATA SAFETY AUDIT — review every line before pushing
# Run git diff and check for: API keys, tokens, passwords, .env values,
# user-specific paths, personal info, organization names, private URLs.
# If ANYTHING sensitive is found: abort, cleanup, fail the task.
git diff main..HEAD

git push -u origin "contribute/user-improvement-$SOURCE_PR"

# Write a clean, generic PR body — no user-specific details
gh pr create --repo "$UPSTREAM_OWNER/$UPSTREAM_REPO" \
  --title "Contributed improvement: <original PR title>" \
  --body "$(cat <<'PRBODY'
## Contributed Self-Improvement

### Observation
<generalized description of the pattern — no user-specific details>

### Change
<diff summary>

### Eval Evidence
<pass rates only — no session paths, no user repo references>

---
*Contributed via the Cambium self-improvement loop.*
PRBODY
)"

# Cleanup
cd "$REPO_DIR"
rm -rf "$TEMP"
```

#### Step 3b — Contributor mode (fork + PR)

If `upstream_role` is `contributor`:

```bash
# Check if fork exists
FORK_REMOTE=$(grep fork_remote defaults/config.yaml | awk '{print $2}')

if [ "$FORK_REMOTE" = "null" ] || [ -z "$FORK_REMOTE" ]; then
  # Create fork
  gh repo fork "$UPSTREAM_OWNER/$UPSTREAM_REPO" --clone=false
  FORK_URL=$(gh repo view --json url -q .url)
  # TODO: update fork_remote in config.yaml
  FORK_REMOTE="$FORK_URL"
fi

# Clone fork
TEMP=$(mktemp -d)
git clone "$FORK_REMOTE" "$TEMP/fork"
cd "$TEMP/fork"

# Sync fork with upstream
git remote add upstream "$UPSTREAM_URL"
git fetch upstream
git checkout -b "contribute/user-improvement-$SOURCE_PR" upstream/main

# Cherry-pick from user's repo
git remote add user-repo "$REPO_DIR"
git fetch user-repo
git cherry-pick "$MERGE_COMMIT"

# DATA SAFETY AUDIT — review every line before pushing
# Run git diff and check for: API keys, tokens, passwords, .env values,
# user-specific paths, personal info, organization names, private URLs.
# If ANYTHING sensitive is found: abort, cleanup, fail the task.
git diff upstream/main..HEAD

git push -u origin "contribute/user-improvement-$SOURCE_PR"

gh pr create --repo "$UPSTREAM_OWNER/$UPSTREAM_REPO" \
  --title "Contributed improvement: <original PR title>" \
  --body "$(cat <<'PRBODY'
## Contributed Self-Improvement

### Observation
<generalized description of the pattern — no user-specific details>

### Change
<diff summary>

### Eval Evidence
<pass rates only — no session paths, no user repo references>

---
*Contributed via the Cambium self-improvement loop.*
PRBODY
)"

# Cleanup
cd "$REPO_DIR"
rm -rf "$TEMP"
```

#### Step 4 — Complete

Complete with the upstream PR URL.

## Failure Modes

- **Data safety violation**: If the diff contains credentials, secrets, private user data, or user-specific paths — **abort immediately**. Clean up the temp directory. Fail the task with a clear explanation of what was found. Never push.
- **Cherry-pick conflict**: The upstream repo may have diverged. Try `git cherry-pick --strategy-option theirs` for trivial conflicts, otherwise fail with details.
- **Fork out of date**: If the fork is stale, `git fetch upstream` + rebase before cherry-picking.
- **No push access**: If author mode fails with permission denied, suggest switching to contributor mode.
- **Duplicate PR**: Check if a PR for this improvement already exists before creating one: `gh pr list --repo <upstream> --state all --search "user-improvement-$SOURCE_PR"`.
- **Feature flag disabled**: If `contribute_upstream` is `false` or missing, fail immediately — do not proceed.
