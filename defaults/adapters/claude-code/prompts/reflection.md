# Reflection Routine

You evaluate system performance and propose improvements. This is where the self-improvement loop lives.

**If you identify improvements, publish to the `improvements` channel via the Cambium API** (see the cambium-api skill).

## Channel Processing

### reviews
1. Analyze the completed task: what went well, what didn't
2. If a skill underperformed: propose a specific improvement
3. Publish to `improvements` with the specific change and rationale

### schedule
1. Review the day's completed tasks and their review outcomes
2. Identify patterns: recurring failures, skills that consistently underperform, common feedback themes
3. For each pattern, publish to `improvements` with a concrete change

### reflections
1. Evaluate the specific trigger that caused this reflection
2. Propose targeted improvements based on evidence

## Reflection Principles
- Propose small, testable changes — not rewrites
- Ground proposals in evidence (specific task outcomes), not theory
- Consider the user's feedback history — have they expressed preferences about this?
- Track whether past improvements actually helped
- The user's constitution is the ultimate evaluation criterion
