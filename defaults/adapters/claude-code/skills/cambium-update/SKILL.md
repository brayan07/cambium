---
name: cambium-update
description: Merge upstream Cambium framework changes into the user's repo
---

# Cambium Update

This skill handles merging upstream framework changes into the user's Cambium repo. It is used by the executor when processing upstream merge work items. The sentry detects upstream changes and routes them through the coordinator and planner.

## Prerequisites

- The repo must have an `upstream` remote: `git remote get-url upstream`
- `.cambium-version` must exist with the last-synced upstream commit hash

## Task Types

### UPSTREAM MERGE — IMPLEMENT

Merge all upstream changes onto a branch and push it. A second task (EVAL + PR) handles verification and PR creation.

**Inputs** (from work item description): upstream commit, base commit.

#### Step 1 — Classify changed files

Determine which files changed upstream and classify each:

```bash
REPO_DIR=$(git rev-parse --show-toplevel)
cd "$REPO_DIR"
git fetch upstream

# All files changed upstream since last sync
git diff "$BASE_COMMIT..upstream/main" --name-only
```

For each changed file, check if the user also modified it:

```bash
git diff "$BASE_COMMIT..HEAD" -- "$FILE" | head -1
```

- If empty: **trivial** — user hasn't touched it, take upstream's version
- If non-empty: **conflicting** — both sides modified, needs three-way merge

#### Step 2 — Create merge branch

```bash
REPO_DIR=$(git rev-parse --show-toplevel)
cd "$REPO_DIR"
git fetch upstream
SHORT_HASH=$(echo "$UPSTREAM_COMMIT" | head -c 8)
BRANCH="merge/upstream-$SHORT_HASH"
git checkout -b "$BRANCH"
```

If the branch already exists (previous partial attempt), check its state before continuing.

#### Step 2 — Apply trivial files

Trivial files are ones the user hasn't modified since the last sync — take upstream's version directly:

```bash
for FILE in $TRIVIAL_FILES; do
  mkdir -p "$(dirname "$FILE")"
  git show "upstream/main:$FILE" > "$FILE"
  git add "$FILE"
done
```

Also handle:
- **Upstream deletions**: `git diff "$BASE_COMMIT..upstream/main" --diff-filter=D --name-only` — remove those files
- **Upstream additions**: `git diff "$BASE_COMMIT..upstream/main" --diff-filter=A --name-only` — create directories as needed and add new files

Commit: `git commit -m "Merge upstream trivial files (N files from $SHORT_HASH)"`

#### Step 3 — Three-way merge conflicting files

For each file in the conflicting list:

1. **Read three versions**:
   ```bash
   git show "$BASE_COMMIT:$FILE" > /tmp/upstream-old.txt     # common ancestor
   git show "upstream/main:$FILE" > /tmp/upstream-new.txt     # upstream's version
   cat "$FILE" > /tmp/user-current.txt                        # user's version
   ```

2. **Understand both sets of changes**:
   - Upstream intent: `git log "$BASE_COMMIT..upstream/main" -- "$FILE"` — read commit messages
   - User intent: `git log "$BASE_COMMIT..HEAD" -- "$FILE"` — read commit messages

3. **Generate merged version** following these principles:
   - User customizations take precedence in areas of genuine conflict
   - Upstream structural changes (new sections, reorganized code) should be adopted when they don't conflict with user changes
   - For prompts (.md): preserve the user's tone and specific instructions while incorporating upstream's new capabilities or sections
   - For YAML config: merge keys — user overrides win for shared keys, upstream additions are included
   - If `git show` fails for a file at base commit, treat it as a new file from upstream

4. **Commit with explanation**:
   ```bash
   git add "$FILE"
   git commit -m "Merge conflicting file: $FILE

   Upstream changes: <summary>
   User changes preserved: <summary>"
   ```

Track merge decisions for each file — the eval+PR task will need them.

#### Step 4 — Push and store context

```bash
git push -u origin "$BRANCH"
```

Store context for the next task:

```bash
curl -s -X PATCH "$CAMBIUM_API_URL/work-items/ITEM_ID/context" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "branch": "<BRANCH>",
    "upstream_commit": "<UPSTREAM_COMMIT>",
    "base_commit": "<BASE_COMMIT>",
    "trivial_count": N,
    "conflicting_count": K,
    "merge_decisions": {
      "<file1>": "Upstream added new section X; user had customized section Y — kept both",
      "<file2>": "User override on key Z preserved; upstream additions A, B included"
    }
  }'
```

Complete with a summary of the merge work done.

### UPSTREAM MERGE — EVAL + PR

Verify the merge branch and create a PR if everything passes.

**Inputs** (from work item context, set by the implement task): `branch`, `upstream_commit`, `base_commit`, `trivial_count`, `conflicting_count`, `merge_decisions`.

#### Step 1 — Check out the merge branch

```bash
REPO_DIR=$(git rev-parse --show-toplevel)
cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
```

#### Step 2 — Run canary eval

```bash
.venv/bin/python -m cambium eval defaults/evals/canary-cascade.yaml \
  --repo-dir "$REPO_DIR"
```

If the canary **fails**: fail the task with details about which routines/assertions failed. Do not create a PR. The planner will escalate for human intervention.

#### Step 3 — Fix minor issues if possible

If eval issues are fixable (e.g., a merge produced invalid YAML, a missing import), fix the issue on the branch, re-run the canary, and proceed. Only fail the task if the issue is fundamental.

#### Step 4 — Create the PR

```bash
echo "$UPSTREAM_COMMIT" > .cambium-version
git add .cambium-version
git commit -m "Update .cambium-version to $SHORT_HASH"
git push origin "$BRANCH"

# Note: gh pr create may fail with branch names containing slashes.
# Use gh api as fallback:
# gh api repos/OWNER/REPO/pulls -X POST -f title="..." -f head="$BRANCH" -f base="main" -f body="..."
gh pr create \
  --title "Merge upstream framework changes ($SHORT_HASH)" \
  --body "$(cat <<'PRBODY'
## Upstream Merge

**Commits merged:** N (from BASE_COMMIT to UPSTREAM_COMMIT)
**Trivial files:** M (user unchanged — took upstream version)
**Conflicting files:** K (AI-assisted three-way merge)

## Upstream Changelog
<git log summary>

## Merge Decisions
<per-file explanation for each conflicting file, from context>

## Eval Results
- **Canary cascade:** PASS (all N assertions passed)

---
*Automatically generated by the Cambium upstream sync engine.*
PRBODY
)"
```

Complete with the PR URL.
