# wf-ship

## Purpose

Orchestrate the “finalize & ship” phase: run quality checks, run regression tests, commit, merge to `main`, and push.

This workflow is independent from `wf-dev` and is meant to be used when the implementation work is essentially done.

## Contract (must follow)

1. Read all user-attached `@...` context first.
   - If required context is missing, ask for the exact `@...` files/info and stop.
2. Classify the current repo state (A/B/C/D) and state confidence.
3. Produce a Plan-mode checklist To-do, where tasks include “run another Cursor command”.
4. Propose the next command as a suggestion only.
5. This command does not auto-transition:
   - Do not output a slash command as a standalone line.
   - Use `NEXT_COMMAND: /...` (inline) to make it easy to copy without auto-running.

## Inputs (ask if missing)

- Goal: what “ship” means here (PR? main push? release note?) (optional)
- Current status:
  - Current branch name
  - Whether changes are already committed
  - Whether `main` is already merged
- If relevant: any docs that should be updated before shipping (`@docs/...`)

## Classification (A/B/C/D → recommended next command)

- **A: Uncommitted changes exist** (working tree dirty) → `NEXT_COMMAND: /quality-check`
- **B: Changes committed on a work branch** (ready to merge) → `NEXT_COMMAND: /merge`
- **C: Already on `main` and ahead of `origin/main`** → `NEXT_COMMAND: /push`
- **D: Nothing to ship** (clean + not ahead) → stop and explain

## Standard To-dos to include

Include these phases unless the classification clearly allows skipping:

- [ ] First: run `NEXT_COMMAND: /docs-discover` (discover relevant docs; attach what’s needed)
- [ ] Run quality checks (`NEXT_COMMAND: /quality-check`)
- [ ] Run regression tests (`NEXT_COMMAND: /regression-test`)
- [ ] Commit changes (`NEXT_COMMAND: /commit`)
- [ ] Merge to `main` (`NEXT_COMMAND: /merge`)
- [ ] Push `main` (`NEXT_COMMAND: /push`)

## Output (response format)

### Context read

- `@...` files read
- Shipping goal (if provided)

### Classification

- Case: A / B / C / D (confidence: high/medium/low)
- Evidence: (bullets)
- Skip decisions: which phases can be skipped and why

### Plan (To-do)

- [ ] ... (include purpose / inputs / done criteria per item)

### Next (manual)

- `NEXT_COMMAND: /...`

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/quality-check.mdc`
- `@.cursor/rules/test-strategy.mdc`
- `@.cursor/rules/commit-message-format.mdc`
