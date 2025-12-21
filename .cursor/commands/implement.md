# implement

## Purpose

Implement the selected task (code changes only; no tests in this step).

## When to use

- After selecting a task and creating a branch (typically after `task-select`)
- Any time you need to implement a scoped change that is already agreed on

## Inputs (attach as `@...`)

- `@docs/REQUIREMENTS.md` (recommended)
- `@docs/IMPLEMENTATION_PLAN.md` (recommended for context; **do not** reference it in code comments)
- Any relevant source files (`@src/...`) or configs (`@config/...`) if the user already knows them

## Constraints

- Do **not** add comments that reference `@docs/IMPLEMENTATION_PLAN.md` inside source code.
- If you need codebase context, use repo search tools (e.g., `grep`, semantic search) rather than guessing.

## Steps

1. Confirm scope and acceptance criteria (1–3 bullet points).
2. Inspect existing code paths and patterns; identify the minimal set of files to change.
3. Implement the change.
4. Do a quick sanity check (basic execution path review; avoid long-running processes unless requested).

## Output (response format)

- **Scope recap**: what changed (1–3 bullets)
- **Files changed**: list of paths
- **Notes**: any trade-offs, follow-ups, or risks
- **Next (manual)**: `NEXT_COMMAND: /test-create`

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/refactoring.mdc`
