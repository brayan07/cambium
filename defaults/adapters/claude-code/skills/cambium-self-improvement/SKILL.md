---
name: cambium-self-improvement
description: Self-improvement loop — detection, triage, planning, execution, review, and upstream sync. Use this skill whenever processing self-improvement proposals, upstream updates, upstream contributions, or any work item with context.type of self_improvement, upstream_merge, or upstream_contribution.
---

# Cambium Self-Improvement

Cambium can observe its own behavior, propose changes to tunable files (prompts, skills, configs), test them via eval, and deploy improvements through human-reviewed PRs. Upstream framework sync (inbound merges, outbound contributions) flows through the same pipeline.

```
Detection (sentry, consolidator)
  → Triage (coordinator)
    → Planning (planner)
      → Execution (executor)
        → Review (reviewer)
```

## Which reference to read

Each routine reads **only** its relevant reference file. Do not read files for other stages.

| Your routine | Read this file | What it covers |
|---|---|---|
| **sentry** | `references/detection.md` | Operational pattern detection, upstream update checks |
| **memory-consolidator** | `references/detection.md` | Content-based pattern detection, upstream contribution detection |
| **coordinator** | `references/triage.md` | Work item creation for self-improvement, upstream update, and upstream contribution payloads |
| **planner** | `references/planning.md` | Gate checks (GitHub remote, PR budget, tunable manifest) and decomposition for all three context types |
| **executor** | `references/execution.md` | Self-improvement Task 1 (eval + baseline) and Task 2 (test + PR). For upstream merge/contribution tasks, use the `cambium-update` and `cambium-contribute` skills instead. |
| **reviewer** | `references/review.md` | Additional scrutiny criteria for self-improvement work items |
