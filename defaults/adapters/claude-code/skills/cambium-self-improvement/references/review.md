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
