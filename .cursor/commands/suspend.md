# suspend

## Purpose

Pause work safely: record progress, document what's incomplete, and create a WIP commit.

## When to use

- You need to stop mid-task but want a clean resumption point
- Context switching to another task/branch

## Inputs (attach as `@...`)

- Any planning/tracking documents where progress should be recorded (optional)

**Note**: If no tracking document is attached, progress will be recorded in the WIP commit message only.

## Steps

1. If a tracking document is attached, record current progress there (use a clear "in progress" marker).
2. Create a WIP commit that explicitly lists completed vs incomplete items.

## WIP commit message example

```text
chore: WIP - <task name>

- Done: implemented xxx
- TODO: add tests
- TODO: run quality checks

WIP: suspended
```

## Output (response format)

- **Done**: what is finished
- **TODO**: what remains
- **Resume notes**: any pitfalls, commands, or context needed
- 