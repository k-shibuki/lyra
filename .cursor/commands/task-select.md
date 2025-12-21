# task-select

## Purpose

Select exactly one implementation task and create a work branch for it.

## When to use

- Start of the development workflow (used by `wf-dev`)
- Any time you need to pick the next unit of work from the plan
- After `discover-docs` to select a task from discovered documents

## Inputs (attach as `@...`)

- Any planning/task documents (e.g. `@docs/IMPLEMENTATION_PLAN.md`, `@docs/TODO.md`, issue files)
- User instructions describing the task to work on

**Note**: This command does not require a specific document format. It will extract tasks from whatever documents or instructions the user provides.

## Steps

1. Review the attached documents and/or user instructions to identify candidate tasks.
2. If no documents are attached and no clear task is given, ask the user what to work on.
3. Pick **exactly one** task considering:
   - User's explicit request (highest priority)
   - Priority and dependencies (if specified in documents)
   - Logical ordering of work
4. Explain why this task is the best next step.
5. If the task is high-risk/high-priority, summarize impact scope and risks up front.
6. Ask the user for approval **before** creating a branch.
7. After approval, create a branch using:

```bash
feature/{short-description}
```

Or if phases are defined in the plan:

```bash
feature/phase-{N}-{M}-{short-description}
```

## Output (response format)

- **Selected task**: title + short description
- **Source**: which document(s) or user instruction the task came from
- **Rationale**: why now, dependency notes
- **Risk/impact** (if applicable): affected areas + rollback concerns
- **Branch name**: proposed (and created if approved)
- **Next (manual)**: `NEXT_COMMAND: /implement`

## Related rules

- `@.cursor/rules/code-execution.mdc`

## Used by workflows

- `wf-dev`