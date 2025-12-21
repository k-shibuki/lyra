# task-select

## Purpose

Select exactly one implementation task and create a work branch for it.

## When to use

- Start of the development workflow (used by `wf-dev`)
- Any time you need to pick the next unit of work from the plan

## Inputs (attach as `@...`)

- `@docs/IMPLEMENTATION_PLAN.md` (required)

## Steps

1. Read `@docs/IMPLEMENTATION_PLAN.md` and identify candidate tasks.
2. Pick **exactly one** task considering priority and dependencies.
3. Explain why this task is the best next step.
4. If the task is high-risk/high-priority, summarize impact scope and risks up front.
5. Ask the user for approval **before** creating a branch.
6. After approval, create a branch using:

```bash
feature/phase-{N}-{M}-{short-description}
```

## Output (response format)

- **Selected task**: title + short description
- **Rationale**: why now, dependency notes
- **Risk/impact** (if applicable): affected areas + rollback concerns
- **Branch name**: proposed (and created if approved)
- **Next (manual)**: `NEXT_COMMAND: /implement`

## Related rules

- `@.cursor/rules/code-execution.mdc`

## Used by workflows

- `wf-dev`