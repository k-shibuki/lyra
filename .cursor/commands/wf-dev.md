# wf-dev

## Purpose

Orchestrate development work: read the provided context, select the next task, and output a Plan-mode To-do checklist that uses the single-purpose Cursor commands.

## Contract (must follow)

1. Read all user-attached `@...` context first.
   - If required context is missing, ask for the exact `@...` files/info and stop.
2. Summarize: goal, chosen task (one), constraints/risks.
3. Produce a Plan-mode checklist To-do, where tasks include “run another Cursor command”.
4. Propose the next command **as a suggestion only**.
5. This command **does not auto-transition**:
   - Do **not** output a slash command as a standalone line.
   - Use `NEXT_COMMAND: /...` (inline) to make it easy to copy without auto-running.

## Standard workflow (encode as To-dos)

- `docs-discover` (discover related docs first)
- `task-select`
- `implement`
- `test-create`
- `test-review`
- `quality-check`
- `regression-test`
- `commit`
- `merge`
- `push`
- `suspend` (if needed)

## Output (response format)

### Context read

- `@...` files read
- Goal (1–2 lines)
- Chosen task (one) + rationale
- Risks/constraints

- [ ] First: run `NEXT_COMMAND: /docs-discover` (discover relevant docs; attach what’s needed)
- [ ] Run: `/task-select`

### Plan (To-do)

- [ ] ... (include purpose / inputs / done criteria per item)

Must include these phases (as To-dos):

- [ ] Run: `/implement`
- [ ] Run: `/test-create`
- [ ] Run: `/test-review`
- [ ] Run: `/quality-check`
- [ ] Run: `/regression-test`
- [ ] Run: `/commit`
- [ ] Run: `/merge`
- [ ] Run: `/push`

### Next (manual)

- `NEXT_COMMAND: /docs-discover`

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/test-strategy.mdc`
- `@.cursor/rules/refactoring.mdc`
- `@.cursor/rules/commit-message-format.mdc`

## References

- `@docs/IMPLEMENTATION_PLAN.md`
- `@docs/REQUIREMENTS.md`
- `@.cursor/commands/scripts-help.md`