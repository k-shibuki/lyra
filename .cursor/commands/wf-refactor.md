# wf-refactor

## Purpose

Orchestrate refactoring work: read the provided context, choose the refactoring mode, and output a Plan-mode To-do checklist that uses the single-purpose refactoring commands.

This workflow is independent from `wf-dev`.

## Contract (must follow)

1. Read all user-attached `@...` context first.
   - If required context is missing, ask for the exact `@...` files/info and stop.
2. Decide which refactoring mode applies (A or B) and explain why.
3. Produce a Plan-mode checklist To-do, where tasks include “run another Cursor command”.
4. Propose the next command as a suggestion only.
5. This command does not auto-transition:
   - Do not output a slash command as a standalone line.
   - Use `NEXT_COMMAND: /...` (inline) to make it easy to copy without auto-running.

## Inputs (ask if missing)

- Refactor goal (what to improve) and constraints (behavior must stay the same? allowed changes?)
- Target scope (`@src/...`, `@tests/...`) or at least module/file names
- Symptoms (if refactor is driven by a bug or pain point)
- Requirements/spec (`@docs/REQUIREMENTS.md`) if behavior must remain aligned

## Modes

### Mode A: Cross-module integration / contract refactor

Use when:

- Interfaces/contracts between modules need reshaping
- Types/dataflow/async coordination breaks across module boundaries

Suggested companion command:

- `NEXT_COMMAND: /integration-design`

### Mode B: Split a bloated module (extract module)

Use when:

- A file/module has too many responsibilities
- You want to extract cohesive sub-modules with a small, stable API

Suggested primary command:

- `NEXT_COMMAND: /refactoring`

## Handoff to `wf-debug` (when the problem is not clearly a refactor yet)

Use `wf-refactor` when the goal and constraints are clear and you are ready to restructure.  
If the issue is primarily “something is broken” and you do not yet have a stable reproduction/evidence, hand off to debugging first.

Handoff signals (examples):

- You cannot state the expected vs actual behavior clearly.
- There is no minimal repro, logs, or failing test to anchor the refactor.
- The problem might be a parser/selector failure or a localized bug fix.

In those cases, propose:

- `NEXT_COMMAND: /wf-debug`

## Standard To-dos to include

- [ ] Run: `/refactoring` (Mode A or B)
- [ ] If Mode A: run `NEXT_COMMAND: /integration-design` (contracts/sequence/type alignment)
- [ ] Run quality checks (`NEXT_COMMAND: /quality-check`)
- [ ] If this change should be merged: run tests + commit + merge/push

## Output (response format)

### Context read

- `@...` files read
- Constraints / acceptance criteria

### Mode decision

- Mode: A or B
- Rationale:
- Risks:

### Plan (To-do)

- [ ] ... (include purpose / inputs / done criteria per item)

### Next (manual)

- `NEXT_COMMAND: /refactoring` (or `/integration-design` for Mode A)

## Related rules

- `@.cursor/rules/refactoring.mdc`
- `@.cursor/rules/integration-design.mdc`
- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/quality-check.mdc`
