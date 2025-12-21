# implement

## Purpose

Implement the selected task (code changes only; no tests in this step).

## When to use

- After selecting a task and agreeing on an implementation plan (typically after `task-plan`)
- Any time you need to implement a scoped change that is already agreed on

## Inputs (attach as `@...`)

- Any context documents the user wants to provide (requirements, specs, plans, etc.)
- Any relevant source files (`@src/...`) or configs (`@config/...`) if the user already knows them

**Note**: Specific document attachments are optional. This command will actively search the codebase for necessary context.

## Constraints

- Do **not** add comments that reference planning documents inside source code.
- Use repo search tools (e.g., `grep`, semantic search) to find necessary context rather than guessing or asking the user for every file.

## Steps

1. Confirm scope and acceptance criteria (1–3 bullet points) based on:
   - Attached documents (if any)
   - User instructions
   - Previous `task-plan` output (if available in conversation)
2. **Actively search the codebase** to understand:
   - Existing code paths and patterns
   - Related modules and dependencies
   - Coding conventions used in the project
3. Identify the minimal set of files to change.
4. Implement the change.
5. Do a quick sanity check (basic execution path review; avoid long-running processes unless requested).

## Output (response format)

- **Scope recap**: what changed (1–3 bullets)
- **Files changed**: list of paths
- **Context discovered**: key files/patterns found via search (if relevant)
- **Notes**: any trade-offs, follow-ups, or risks
- **Next (manual)**: `NEXT_COMMAND: /test-create`

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/refactoring.mdc`
