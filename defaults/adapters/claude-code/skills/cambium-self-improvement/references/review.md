# Review

Work items from the self-improvement loop (description contains `SELF-IMPROVEMENT TASK`) require additional scrutiny beyond normal review criteria.

## Task 1 (eval + baseline) — check that:
- The eval config actually tests the behavior described in the observation
- Assertions are meaningful (not trivially true or tautological)
- The baseline result is reasonable (not all-fail or all-pass for wrong reasons)
- The config override correctly describes the proposed change

## Task 2 (comparison + PR) — check that:
- The canary eval was run and passed
- The comparison eval shows genuine improvement, not noise
- The PR was created with the `self-improvement` label
- The change in the PR matches what the override described
- The PR body includes eval scores and evidence

## Red flags to reject on:
- **Gaming the metric**: eval assertions that pass regardless of the change
- **Trivially true**: the eval scenario doesn't exercise the behavior being changed
- **Missing canary**: the canary eval was skipped or its results not reported
- **Scope creep**: the PR modifies files beyond the declared target
- **PR flow bypassed**: the result claims repo files were edited, but no PR URL
  is referenced AND `git -C "$CAMBIUM_REPO_DIR" status --porcelain` shows
  uncommitted changes. This means the executor wrote directly to the live
  tree instead of going through a worktree. Reject with feedback like:
  *"Apply via worktree + PR, not direct edit. Run `git worktree add
  /tmp/cambium-improve-$$ -b <branch>` and redo the change there, then
  `gh pr create --label self-improvement`."*

## PR-flow check (every self-improvement task)

Before accepting any task whose `result` claims to have edited files under
`src/`, `tests/`, `defaults/`, `ui/src/`, or any tunable manifest entry:

1. Look for a PR URL in the result text (`gh pr` output, `https://github.com/.../pull/`).
2. Run `git -C "$CAMBIUM_REPO_DIR" status --porcelain` — the working tree
   should be clean. If files are dirty AND the dirty files match what the
   task said it touched, the executor bypassed the PR flow. Reject.
3. If a PR URL is present, verify the PR exists and is labeled `self-improvement`:
   `gh pr view <url> --json labels,state -q '.labels[].name, .state'`.

This check is the human-review safety net for fix (c) of brayan07/cambium#30.
