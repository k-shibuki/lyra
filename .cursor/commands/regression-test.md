# regression-test

## Purpose

Run the full test suite to detect regressions.

## When to use

- After quality checks pass (typically after `quality-check`)
- Before merging/pushing changes

## Inputs

- None required (but attach failing logs/output if rerunning after a failure)

## How to run (recommended)

Use `scripts/test.sh` (async + polling):

```bash
./scripts/test.sh run tests/
./scripts/test.sh check
./scripts/test.sh get
./scripts/test.sh kill  # only if you need to abort
```

Polling example:

```bash
./scripts/test.sh run tests/
for i in {1..180}; do
    sleep 1
    status=$(./scripts/test.sh check 2>&1)
    echo "[$i] $status"
    if echo "$status" | grep -qE "(DONE|passed|failed|skipped|deselected)"; then
        break
    fi
done
./scripts/test.sh get
```

Completion logic:

- `check` returns `DONE` when test output contains `passed`/`failed`/`skipped`/`deselected`
- Otherwise it uses file modification time (no updates for 5s => `DONE`)

## Output (response format)

- **Summary**: passed / failed / skipped
- **Failures** (if any): list + first actionable traceback snippets

## Related rules

- `@.cursor/rules/code-execution.mdc`