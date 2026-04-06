---
name: skillgrade
description: >
  Run Skillgrade to evaluate agent skills. Use when generating eval YAML from a
  skill definition, running evaluations, or viewing results.
---

# Skillgrade — Skill Evaluation

Skillgrade is a CLI tool that provides "unit tests" for agent skills. It generates
evaluation configs from SKILL.md files, runs trials against an agent, and scores
results using deterministic and LLM-rubric graders.

**Binary:** `npx skillgrade` (installed in the Cambium project's node_modules)

## Operations

### generate-eval

Generate an `eval.yaml` for a skill from its SKILL.md.

```bash
cd <skill-directory>          # must contain SKILL.md
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" npx skillgrade init
```

- Reads SKILL.md and produces `eval.yaml` with tasks and graders
- Use `--force` to overwrite an existing eval.yaml
- Requires an API key for the LLM that generates the eval config

After generation, review and edit `eval.yaml` — the generated config is a starting
point, not a finished product. Verify that tasks test the skill's actual behavior
and graders check meaningful outcomes.

### run-eval

Run evaluations defined in `eval.yaml`.

```bash
cd <skill-directory>
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" npx skillgrade [options]
```

**Presets** (control trial count):

| Preset | Trials | Use case |
|--------|--------|----------|
| `--smoke` | 5 | Quick feedback during development |
| `--reliable` | 15 | Estimate pass rate before merging |
| `--regression` | 30 | High-confidence regression detection |

**Common flags:**

| Flag | Purpose |
|------|---------|
| `--eval=NAME` | Run a specific eval (comma-separated for multiple) |
| `--agent=claude` | Force Claude as the agent (default: auto-detect from API key) |
| `--provider=local` | Run locally instead of Docker (use in CI or when Docker unavailable) |
| `--parallel=N` | Run N trials concurrently |
| `--ci` | Exit non-zero if pass rate is below threshold |
| `--threshold=0.8` | Set pass rate threshold (default 0.8) |
| `--validate` | Verify graders against reference solutions before full run |

**Example — smoke test a skill with Claude:**

```bash
cd defaults/adapters/claude-code/skills/my-skill
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" npx skillgrade --smoke --agent=claude --provider=local
```

### report

View evaluation results.

```bash
npx skillgrade preview            # CLI output
npx skillgrade preview browser    # Web UI at http://localhost:3847
```

Results include per-task scores, grader breakdowns, and trial-level details.

## eval.yaml Reference

```yaml
version: "1"

defaults:
  agent: claude
  provider: local
  trials: 5
  timeout: 300
  threshold: 0.8

tasks:
  - name: task-identifier
    instruction: |
      Clear task description for the agent
    workspace:
      - src: fixtures/input.txt
        dest: input.txt
    graders:
      - type: deterministic
        run: bash graders/check.sh
        weight: 0.7
      - type: llm_rubric
        rubric: |
          Evaluation criteria here
        weight: 0.3
```

**Grader types:**
- `deterministic` — runs a script, expects JSON stdout with `score` (0.0-1.0) and `details`
- `llm_rubric` — evaluates the agent's transcript against qualitative criteria

String fields (`instruction`, `rubric`) support file references: `instruction: instructions/task.md`

## Important

- Always run from the skill's directory (where SKILL.md and eval.yaml live)
- The `--provider=local` flag runs without Docker — use this unless isolation is needed
- Agent is auto-detected from API key: `ANTHROPIC_API_KEY` -> Claude, `GEMINI_API_KEY` -> Gemini
- Start with `--smoke` during development, graduate to `--reliable` before merging
- Grade outcomes, not steps — verify the agent produced the right result, not that it ran specific commands
