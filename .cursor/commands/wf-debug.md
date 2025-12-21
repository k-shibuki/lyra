# wf-debug

## Purpose

Orchestrate debugging: read the provided context, classify the problem, and output a Plan-mode To-do list that calls other Cursor commands (manually).

Note: This workflow is independent from `wf-dev`.

## Contract (must follow)

1. Read all user-attached `@...` context first.
   - If required context is missing, ask for the exact `@...` files/info and stop.
2. Classify the issue into A/B/C and state confidence.
3. Produce a Plan-mode checklist To-do, where tasks include “run another Cursor command”.
4. Propose the next command **as a suggestion only**.
5. This command **does not auto-transition**:
   - Do **not** output a slash command as a standalone line.
   - Use `NEXT_COMMAND: /...` (inline) to make it easy to copy without auto-running.

## Inputs (ask if missing)

- Symptom (expected vs actual)
- Minimal repro steps
- Recent error/log/stack trace
- Relevant files: `@src/...`, `@config/...`, `@docs/...`

## Classification (A/B/C → next command)

- **A: Cross-module integration** → `NEXT_COMMAND: /integration-design`
- **B: General bug** → `NEXT_COMMAND: /bug-analysis`
- **C: HTML parser/selector failure** → `NEXT_COMMAND: /parser-repair`

## Handoff to `wf-refactor` (when debugging turns into restructuring)

Use `wf-debug` to identify and fix the bug. However, **handoff to the refactor workflow** when a structural change is the safest way to eliminate the issue or prevent recurrence.

Handoff signals (examples):

- The bug is caused by unclear boundaries, mixed responsibilities, or repeated “fix the symptom” patches.
- Fix requires reshaping contracts/APIs across modules (not just a local patch).
- A bloated module makes the correct fix risky or hard to validate.
- You need to split a module/package to restore cohesion and testability.

In those cases, propose:

- `NEXT_COMMAND: /wf-refactor`

## Standard To-dos to include

- [ ] Run the classification-specific command (A/B/C)
- [ ] Run quality checks (`NEXT_COMMAND: /quality-check`)
- [ ] Run regression tests (`NEXT_COMMAND: /regression-test`)
- [ ] Commit (`NEXT_COMMAND: /commit`)
- [ ] If needed: merge + push (`NEXT_COMMAND: /merge-complete`, then `NEXT_COMMAND: /push`)

## Output (response format)

### Context read

- `@...` files read
- Key constraints/acceptance criteria

### Classification

- Case: A / B / C (confidence: high/medium/low)
- Evidence: (bullets)
- Unknowns: (bullets, if any)

### Plan (To-do)

- [ ] ... (include purpose / inputs / done criteria per item)

### Next (manual)

- `NEXT_COMMAND: /...`

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/integration-design.mdc`
- `@.cursor/rules/refactoring.mdc`