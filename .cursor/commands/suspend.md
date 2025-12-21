# suspend

## Purpose

Pause work safely: record progress, document what’s incomplete, and create a WIP commit.

## When to use

- You need to stop mid-task but want a clean resumption point
- Context switching to another task/branch

## Inputs (attach as `@...`)

- `@docs/IMPLEMENTATION_PLAN.md` (recommended)

## Steps

1. Record current progress in `@docs/IMPLEMENTATION_PLAN.md` (use a clear “in progress” marker).
2. Create a WIP commit that explicitly lists completed vs incomplete items.

## WIP commit message example

```text
chore: WIP - Phase X.Y <task name>

- Done: implemented xxx
- TODO: add tests
- TODO: run quality checks

WIP: suspended
```

## Output (response format)

- **Done**: what is finished
- **TODO**: what remains
- **Resume notes**: any pitfalls, commands, or context needed
- **Next (manual)**: resume with the appropriate single-purpose command (e.g. `NEXT_COMMAND: /implement`, `NEXT_COMMAND: /bug-analysis`, `NEXT_COMMAND: /test-create`)